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
import time
import json
import base64
import urllib.request
import urllib.error

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


# ---------------------------------------------------------------------------
# Frame grabber â€“ /snap returns a single JPEG immediately
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
