#!/usr/bin/env python3
"""
Vision Proxy for ESP32 Vision Assistant.

Polls the ESP32 for a "Describe Scene" trigger, grabs a snapshot via
/snap, sends it to a fast vision LLM, then POSTs the text back.

Priority (fastest first):
  1. Groq  (llama-4-scout / llama-3.2-vision)  ~1-3 s  FREE
     $env:GROQ_API_KEY = "gsk_..."          â† get free key at console.groq.com
  2. HuggingFace Inference API              ~30-90 s  (slower fallback)
     $env:HUGGINGFACEHUB_API_TOKEN = "hf_..."
  3. Local Gemma model  (requires torch + transformers, very slow without GPU)

Usage:
    python tools/gemma_proxy.py [ESP_IP]
    python tools/gemma_proxy.py 192.168.12.148
"""
import sys
import os
import io
import time
import json
import base64
import urllib.request
import urllib.error
import threading

ESP_IP        = sys.argv[1] if len(sys.argv) > 1 else '192.168.12.148'
BASE_URL      = f'http://{ESP_IP}'
POLL_INTERVAL = 1.0
PROMPT        = (
    'This image is from a small embedded camera and may look noisy, blurry, or colour-shifted — '
    'that is normal. Ignore the image quality entirely. '
    'Focus only on the main subject or object visible and describe what it is and what it is doing '
    'in one short sentence.'
)
PROMPT_POINT  = (
    'A person is pointing at something in this image. '
    'The image is from a small embedded camera and may look very distorted and low quality — '
    'ignore the image quality entirely. '
    'What is the specific object or thing being pointed at? '
    'Answer in five words or fewer, e.g. "a red coffee mug".'
)

PROMPT_AUDIO = (
    'You are MIRA, a small friendly AI assistant built into an embedded device. '
    'The user just spoke the following to you: "{transcript}". '
    'Answer their question or respond to their request directly and helpfully. '
    'Be concise — two sentences maximum. Do NOT repeat or echo what they said. '
    'Respond as if speaking out loud to the user.'
)


# ---------------------------------------------------------------------------
# TTS — Groq Orpheus v1 English
# Note: Orpheus has no Indian-accent voice. 'hannah' is the warmest female
# voice available. The cartoon-robot filter below compensates with a cute,
# high-pitched robotic timbre.
# Valid voices: autumn, diana, hannah (female)  austin, daniel, troy (male)
# Falls back silently if sounddevice not installed.
# ---------------------------------------------------------------------------
_TTS_VOICE = 'hannah'
_TTS_MODEL = 'canopylabs/orpheus-v1-english'


def _apply_cartoon_robot(samples, rate):
    """Pitch-shift up ~35% + ring-modulate at 65 Hz → small cartoon-robot voice."""
    import numpy as np
    # Pitch up: linearly resample to fewer samples, then play at original rate
    # (fewer samples at same rate = plays faster = higher pitch, like a chipmunk/robot)
    factor  = 1
    new_len = max(1, int(len(samples) / factor))
    src_t   = np.linspace(0.0, 1.0, len(samples))
    dst_t   = np.linspace(0.0, 1.0, new_len)
    shifted = np.interp(dst_t, src_t, samples).astype(np.float32)
    # Ring modulation at 65 Hz for a buzzed robotic quality
    t        = np.arange(new_len, dtype=np.float32) / rate
    carrier  = np.sin(2.0 * np.pi * 80.0 * t)
    return (shifted * (0.70 + 0.30 * carrier)).astype(np.float32)


def speak_result(text):
    """Send text to Groq Orpheus TTS and play the WAV in a background thread."""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return
    def _speak():
        try:
            payload = json.dumps({
                'model': _TTS_MODEL,
                'voice': _TTS_VOICE,
                'input': text,
                'response_format': 'wav',
            }).encode()
            req = urllib.request.Request(
                'https://api.groq.com/openai/v1/audio/speech',
                data=payload, method='POST',
                headers={'Authorization': 'Bearer ' + api_key,
                         'Content-Type': 'application/json',
                         'User-Agent': 'Mozilla/5.0'},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                wav_bytes = resp.read()
            # WAV — play directly with sounddevice (no pydub/ffmpeg needed)
            import numpy as np
            import sounddevice as sd
            import wave
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                rate = wf.getframerate()
                n_ch = wf.getnchannels()
                sw   = wf.getsampwidth()
                raw  = wf.readframes(2 ** 30)  # read all; getnframes() unreliable for streaming WAV
            dtype = {1: np.int8, 2: np.int16, 4: np.int32}[sw]
            samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
            samples /= 2 ** (sw * 8 - 1)
            if n_ch == 2:
                # apply effect per channel, then interleave back
                left  = _apply_cartoon_robot(samples[:, 0], rate)
                right = _apply_cartoon_robot(samples[:, 1], rate)
                samples = np.column_stack((left, right))
            else:
                samples = _apply_cartoon_robot(samples, rate)
            print('[tts] Speaking (cartoon-robot filter active)...')
            sd.play(samples, samplerate=rate, blocking=True)
            print('[tts] Done.')
        except ImportError:
            print('[tts] sounddevice not installed — skipping audio playback')
        except Exception as exc:
            print(f'[tts] Error: {exc}')
    threading.Thread(target=_speak, daemon=True).start()


# ---------------------------------------------------------------------------# Frame grabber â€“ /snap returns a single JPEG immediately
# ---------------------------------------------------------------------------
def fetch_frame_jpeg():
    try:
        with urllib.request.urlopen(f'{BASE_URL}/snap', timeout=6) as resp:
            data = resp.read()
        if data[:2] == b'\xff\xd8':
            print(f'[proxy] Snapshot: {len(data)} bytes')
            return data
        print(f'[proxy] /snap returned unexpected data ({len(data)} B)')
    except Exception as exc:
        print(f'[proxy] /snap error: {exc}')
    return None


# ---------------------------------------------------------------------------
# Backend 1 â€“ Groq  (fastest, free tier, needs GROQ_API_KEY)
# ---------------------------------------------------------------------------
def run_groq(jpeg_bytes, prompt=None):
    if prompt is None: prompt = PROMPT
    api_key = os.environ['GROQ_API_KEY']
    model   = os.environ.get('GROQ_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
    b64     = base64.b64encode(jpeg_bytes).decode()
    payload = {
        'model': model,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text',      'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'high'}},
            ],
        }],
        'max_tokens': 150,
    }
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        'https://api.groq.com/openai/v1/chat/completions',
        data=data, method='POST',
        headers={'Authorization': f'Bearer {api_key}',
                 'Content-Type':  'application/json',
                 'User-Agent':    'Mozilla/5.0'},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    return body['choices'][0]['message']['content'].strip()


# ---------------------------------------------------------------------------
# Backend 2 â€“ HuggingFace Inference API  (no install required, but slow)
# ---------------------------------------------------------------------------
def run_hf(jpeg_bytes, prompt=None):
    if prompt is None: prompt = PROMPT
    token = os.environ['HUGGINGFACEHUB_API_TOKEN']
    model = os.environ.get('HF_MODEL', 'meta-llama/Llama-3.2-11B-Vision-Instruct')
    url   = f'https://api-inference.huggingface.co/models/{model}'
    b64   = base64.b64encode(jpeg_bytes).decode()
    payload = {
        'inputs':     {'image': f'data:image/jpeg;base64,{b64}', 'text': prompt},
        'parameters': {'max_new_tokens': 150},
        'options':    {'wait_for_model': True},
    }
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, method='POST',
                                  headers={'Authorization': f'Bearer {token}',
                                           'Content-Type':  'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    if isinstance(body, list) and body:
        return str(body[0].get('generated_text', body[0])).strip()
    return str(body).strip()


# ---------------------------------------------------------------------------
# Backend 3 â€“ Local Gemma4 vision model  (requires: pip install transformers torch pillow)
# Bypasses GemmaInterface and drives the processor directly so the image
# content token is correctly injected into the Gemma4 chat template.
# ---------------------------------------------------------------------------
_local_model     = None  # cached after first load
_local_processor = None

def run_local(jpeg_bytes, prompt=None):
    if prompt is None: prompt = PROMPT
    global _local_model, _local_processor

    missing = []
    for pkg in ('torch', 'transformers', 'PIL'):
        try:
            __import__(pkg)
        except ImportError:
            missing.append('Pillow' if pkg == 'PIL' else pkg)
    if missing:
        return (f'Missing packages: {", ".join(missing)}. '
                f'Run: pip install {" ".join(missing)}\n'
                f'Or set GROQ_API_KEY (free at https://console.groq.com) for instant results.')

    import io
    import torch
    from PIL import Image
    from transformers import AutoProcessor, AutoModelForImageTextToText

    model_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gemma')

    # Load once and cache â€“ subsequent calls are fast
    if _local_processor is None:
        print(f'[proxy] Loading processor from {model_path}...')
        _local_processor = AutoProcessor.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=True)

    if _local_model is None:
        print(f'[proxy] Loading Gemma4 vision model (CPU, first run is slow)...')
        _local_model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype='auto',
            device_map={'': 'cpu'},
            low_cpu_mem_usage=True,
        )
        _local_model.eval()
        print('[proxy] Model ready.')

    # Build chat message WITH the image content item so Gemma4 sees <image> token
    # Resize to 224×224 – vision encoder normalises to this anyway; saves ~6× CPU time
    pil_img  = Image.open(io.BytesIO(jpeg_bytes)).convert('RGB').resize((224, 224), Image.LANCZOS)
    messages = [{'role': 'user', 'content': [
        {'type': 'image'},
        {'type': 'text', 'text': prompt},
    ]}]

    try:
        text = _local_processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        text = _local_processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)

    inputs = _local_processor(text=text, images=[pil_img], return_tensors='pt')

    print('[proxy] Running local inference (may take 60-120 s on CPU – please wait)...')
    import sys as _sys; _sys.stdout.flush()
    with torch.inference_mode():
        out = _local_model.generate(
            **inputs,
            max_new_tokens=30,   # ~1 sentence; shorter = faster
            do_sample=False,
        )

    input_len = inputs['input_ids'].shape[-1]
    result    = _local_processor.decode(out[0][input_len:], skip_special_tokens=True)
    return result.strip()


# ---------------------------------------------------------------------------
# Dispatcher â€“ try backends in order
# ---------------------------------------------------------------------------
def describe_scene(jpeg_bytes, prompt=None):
    if prompt is None:
        prompt = PROMPT
    if os.environ.get('GROQ_API_KEY'):
        try:
            result = run_groq(jpeg_bytes, prompt)
            print(f'[proxy] Groq result: {result[:80]}...')
            return result
        except Exception as exc:
            print(f'[proxy] Groq failed ({exc}) — trying next backend...')

    if os.environ.get('HUGGINGFACEHUB_API_TOKEN'):
        try:
            result = run_hf(jpeg_bytes, prompt)
            print(f'[proxy] HF result: {result[:80]}...')
            return result
        except Exception as exc:
            print(f'[proxy] HF API failed ({exc}) — trying local model...')

    return run_local(jpeg_bytes, prompt)


# ---------------------------------------------------------------------------
# Post result back to ESP32
# ---------------------------------------------------------------------------
def post_result(text):
    data = text.encode('utf-8')
    req  = urllib.request.Request(f'{BASE_URL}/gemma_result', data=data,
                                  method='POST',
                                  headers={'Content-Type': 'text/plain'})
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
        print('[proxy] Result posted to ESP32.')
    except Exception as exc:
        print(f'[proxy] POST error: {exc}')


# ---------------------------------------------------------------------------
# Audio transcription (Groq Whisper) + LLM reply chain
# ---------------------------------------------------------------------------
def _make_multipart(fields, files):
    import random, string
    boundary = ''.join(random.choices(string.ascii_letters, k=20)).encode()
    body = b''
    for name, value in fields:
        body += b'--' + boundary + b'\r\n'
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b'\r\n'
    for name, filename, data in files:
        body += b'--' + boundary + b'\r\n'
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += b'Content-Type: audio/wav\r\n\r\n'
        body += data + b'\r\n'
    body += b'--' + boundary + b'--\r\n'
    return body, f'multipart/form-data; boundary={boundary.decode()}'


def transcribe_audio(wav_bytes):
    """Transcribe WAV bytes using Groq Whisper-large-v3."""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        print('[audio] No GROQ_API_KEY — skipping transcription')
        return None
    try:
        body, ct = _make_multipart(
            [('model', 'whisper-large-v3'), ('language', 'en'), ('response_format', 'json')],
            [('file', 'recording.wav', wav_bytes)],
        )
        req = urllib.request.Request(
            'https://api.groq.com/openai/v1/audio/transcriptions',
            data=body, method='POST',
            headers={'Authorization': f'Bearer {api_key}',
                     'Content-Type': ct,
                     'User-Agent': 'Mozilla/5.0'},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        transcript = result.get('text', '').strip()
        print(f'[audio] Transcript: {transcript[:80]}')
        return transcript
    except Exception as exc:
        print(f'[audio] Whisper error: {exc}')
        return None


def run_audio_chain(wav_bytes):
    """Transcribe then get an LLM reply. Returns the combined result string."""
    transcript = transcribe_audio(wav_bytes)
    if not transcript:
        return 'Sorry, I could not hear that clearly.'
    api_key = os.environ.get('GROQ_API_KEY')
    if api_key:
        try:
            prompt = PROMPT_AUDIO.format(transcript=transcript)
            payload = {
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 80,
            }
            req = urllib.request.Request(
                'https://api.groq.com/openai/v1/chat/completions',
                data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': f'Bearer {api_key}',
                         'Content-Type': 'application/json',
                         'User-Agent': 'Mozilla/5.0'},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
            reply = body['choices'][0]['message']['content'].strip()
            print(f'[audio] Reply: {reply[:80]}')
            return reply
        except Exception as exc:
            print(f'[audio] LLM error: {exc}')
    return f'I heard: \u201c{transcript}\u201d \u2014 but I need an internet connection to answer.'


# ---------------------------------------------------------------------------
# Main polling loop  (runs forever; Ctrl+C to stop)
# ---------------------------------------------------------------------------
def main():
    print(f'[proxy] Polling {BASE_URL}/gemma every {POLL_INTERVAL}s  (Ctrl+C to stop)')
    print('[proxy] Click "Describe Scene" in the web UI to trigger.')
    if os.environ.get('GROQ_API_KEY'):
        model = os.environ.get('GROQ_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
        print(f'[proxy] PRIMARY: Groq ({model}) ~1-3 s')
    elif os.environ.get('HUGGINGFACEHUB_API_TOKEN'):
        print('[proxy] PRIMARY: HuggingFace API (~30-90 s) â€“ for speed set GROQ_API_KEY')
    else:
        print('[proxy] No API key set. For fast results:')
        print('[proxy]   1. Get a FREE Groq key at https://console.groq.com â†’ API Keys')
        print('[proxy]   2. $env:GROQ_API_KEY = "gsk_..."')
        print('[proxy]   3. Restart this script')
        print('[proxy] Falling back to local model (needs torch+transformers)...')

    while True:
        try:
            with urllib.request.urlopen(f'{BASE_URL}/gemma', timeout=5) as resp:
                state = json.loads(resp.read())

            if state.get('pending'):
                ctx   = state.get('ctx', 'describe')
                prompt = PROMPT_POINT if ctx == 'point' else PROMPT
                print(f'[proxy] Trigger received (ctx={ctx}) — fetching snapshot...')
                jpeg = fetch_frame_jpeg()
                if not jpeg:
                    post_result('Error: could not capture frame from camera.')
                else:
                    t0 = time.time()
                    result = describe_scene(jpeg, prompt)
                    print(f'[proxy] Done in {time.time() - t0:.1f} s')
                    post_result(result)
                    speak_result(result)

            # ── Check for new audio recording ──────────────────────────────
            with urllib.request.urlopen(f'{BASE_URL}/audio', timeout=5) as resp:
                audio_state = json.loads(resp.read())
            if audio_state.get('pending'):
                fname = audio_state.get('file', '')
                if fname:
                    print(f'[audio] New recording: {fname} — downloading...')
                    with urllib.request.urlopen(
                            f'{BASE_URL}/audio_dl?f={fname}', timeout=15) as resp:
                        wav_bytes = resp.read()
                    print(f'[audio] Downloaded {len(wav_bytes)} B — transcribing...')
                    t0 = time.time()
                    result = run_audio_chain(wav_bytes)
                    print(f'[audio] Done in {time.time() - t0:.1f} s')
                    post_result(result)
                    speak_result(result)

        except KeyboardInterrupt:
            print('\n[proxy] Stopped.')
            break
        except urllib.error.URLError as exc:
            print(f'[proxy] ESP32 unreachable: {exc}')
        except Exception as exc:
            print(f'[proxy] Error: {exc}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
