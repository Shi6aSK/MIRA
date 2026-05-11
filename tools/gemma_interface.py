import os
import threading
import time
from typing import Optional


def _env_int(name: str, default: int, min_value: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return value if value >= min_value else min_value

class GemmaError(Exception):
    pass


class GemmaInterface:
    """Modular Gemma loader and interface.

    Loads model in background and exposes: status(), generate(prompt, image_path, audio_path)
    """
    def __init__(self, model_path=None):
        self.model_path = model_path or os.path.join(os.getcwd(), 'gemma')
        self._status = 'initializing'
        self._load_err = None
        self.processor = None
        self.model = None
        self.model_type = 'causal'  # or 'image-text'
        self._hf_token = None
        self._hf_model = None
        self._asr = None
        self._asr_err = None
        self._asr_model = os.environ.get('GEMMA_ASR_MODEL', 'openai/whisper-tiny.en')
        self._fast_mode = os.environ.get('GEMMA_FAST_MODE', '1') != '0'
        self._default_max_new_tokens = _env_int('GEMMA_DEFAULT_MAX_NEW_TOKENS', 72, 8)
        self._hf_timeout_sec = _env_int('GEMMA_HF_TIMEOUT_SEC', 45, 20)
        self._lock = threading.Lock()
        self._loader = threading.Thread(target=self._load_model, daemon=True)
        self._loader.start()

    def status(self):
        return self._status

    def reload(self):
        # Start a fresh loader thread
        with self._lock:
            self._status = 'reloading'
            self._load_err = None
            self.processor = None
            self.model = None
        self._loader = threading.Thread(target=self._load_model, daemon=True)
        self._loader.start()

    def _load_model(self):
        try:
            self._status = 'loading'
            # determine target before importing heavy libraries so exception handlers can reference it
            is_local = os.path.isdir(self.model_path)
            target = self.model_path if is_local else "google/gemma-4-2b-it"
            try:
                import torch
                use_cuda = bool(torch.cuda.is_available()) and os.environ.get('GEMMA_FORCE_CPU', '0') != '1'
                if not use_cuda:
                    # Keep one thread free for UI/IO so requests feel more responsive.
                    cpu_threads = _env_int('GEMMA_CPU_THREADS', max(1, (os.cpu_count() or 2) - 1), 1)
                    try:
                        torch.set_num_threads(cpu_threads)
                    except Exception:
                        pass
                    try:
                        torch.set_num_interop_threads(1)
                    except Exception:
                        pass
                model_device = 'auto' if use_cuda else {"": "cpu"}
                model_dtype = torch.float16 if use_cuda else "auto"
            except Exception:
                model_device = {"": "cpu"}
                model_dtype = "auto"
            from transformers import AutoProcessor, AutoModelForCausalLM, AutoModelForImageTextToText
            # Try image-text model first
            try:
                self.processor = AutoProcessor.from_pretrained(
                    target, local_files_only=is_local, trust_remote_code=True)
            except Exception:
                self.processor = AutoProcessor.from_pretrained(target, trust_remote_code=True)

            # Gemma 4 is a conditional-generation (image-text) model; try that first
            try:
                self.model = AutoModelForImageTextToText.from_pretrained(
                    target,
                    torch_dtype=model_dtype,
                    device_map=model_device,
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                    local_files_only=is_local,
                )
                self.model_type = 'image-text'
            except Exception:
                self.model = AutoModelForCausalLM.from_pretrained(
                    target,
                    torch_dtype=model_dtype,
                    device_map=model_device,
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                    local_files_only=is_local,
                )
                self.model_type = 'causal'

            try:
                if model_device == {"": "cpu"}:
                    self.model.to('cpu')
            except Exception:
                pass
            try:
                self.model.eval()
            except Exception:
                pass
            try:
                self.model.generation_config.use_cache = True
            except Exception:
                pass
            self._status = 'ready'
        except Exception as e:
            # Capture load error; if it's a torch DLL init error on Windows, try HF Inference API fallback
            self._load_err = e
            msg = str(e)
            if 'c10.dll' in msg or 'DLL' in msg or isinstance(e, OSError):
                # Try Hugging Face Inference API if token present
                token = os.environ.get('HUGGINGFACEHUB_API_TOKEN')
                model_id = self.model_path if os.path.isdir(self.model_path) else "google/gemma-4-E2B-it"
                if token:
                    try:
                        # ensure we don't require requests; we'll store token/model and mark api mode
                        self._hf_token = token
                        self._hf_model = model_id
                        self._status = 'inference-api (hf)'
                        return
                    except Exception:
                        pass
                # Otherwise surface an error recommending CPU wheel or MSVC
                self._status = f'error: torch_dll ({type(e).__name__})'
            else:
                self._status = f'error: {type(e).__name__}'

    def generate(self, prompt: str, image_path: Optional[str]=None, audio_path: Optional[str]=None, max_new_tokens: int=96):
        if self._status.startswith('error'):
            raise GemmaError('Model loader error')

        try:
            max_new_tokens = int(max_new_tokens)
        except Exception:
            max_new_tokens = self._default_max_new_tokens
        if self._fast_mode:
            max_new_tokens = min(max_new_tokens, self._default_max_new_tokens)
        max_new_tokens = max(8, max_new_tokens)

        # HF Inference API fallback path
        if self._status.startswith('inference-api'):
            # Use HF Inference REST API
            try:
                import requests
                headers = {"Authorization": f"Bearer {getattr(self, '_hf_token', '')}"}
                model = getattr(self, '_hf_model', 'google/gemma-4-E2B-it')
                url = f"https://api-inference.huggingface.co/models/{model}"
                payload = {
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": max_new_tokens,
                        "do_sample": False,
                        "return_full_text": False,
                    },
                    "options": {"wait_for_model": True}
                }
                r = requests.post(url, headers=headers, json=payload, timeout=self._hf_timeout_sec)
                try:
                    j = r.json()
                except Exception:
                    raise GemmaError(f'HF inference failed: {r.status_code} {r.text}')
                # response may be a dict or list
                if isinstance(j, list) and len(j) and isinstance(j[0], dict):
                    # common format: [{'generated_text': '...'}]
                    out = j[0].get('generated_text') or j[0].get('generated_text', str(j[0]))
                    return out
                if isinstance(j, dict):
                    # try common keys
                    for k in ('generated_text', 'text'):
                        if k in j:
                            return j[k]
                    return str(j)
            except Exception as e:
                raise GemmaError(f'HF inference error: {e}')

        if self._status != 'ready':
            raise GemmaError('Model not ready')

        # Transcribe audio if present. ASR pipeline is loaded lazily once.
        audio_text = None
        if audio_path:
            if self._asr is None and self._asr_err is None:
                try:
                    from transformers import pipeline
                    self._asr = pipeline(
                        'automatic-speech-recognition',
                        model=self._asr_model,
                        device_map={"": "cpu"},
                    )
                except Exception as exc:
                    self._asr_err = exc
            if self._asr is not None:
                try:
                    res = self._asr(audio_path)
                    audio_text = res.get('text') if isinstance(res, dict) else str(res)
                except Exception:
                    audio_text = f'[audio:{os.path.basename(audio_path)}]'
            else:
                audio_text = f'[audio:{os.path.basename(audio_path)}]'

        # Prepare text including audio transcription and image marker
        full_prompt = prompt
        if audio_text:
            full_prompt = full_prompt + "\n\nAudio transcript: " + audio_text
        if image_path:
            # If image-text capable, we'll pass the image separately. Otherwise annotate prompt.
            if self.model_type != 'image-text':
                full_prompt = full_prompt + "\n\n[image attached: " + os.path.basename(image_path) + "]"

        # Build inputs and run generation
        try:
            import torch
            # Use processor chat template when available to create proper model prompt
            try:
                if hasattr(self.processor, 'apply_chat_template'):
                    messages = [
                        {"role": "user", "content": full_prompt},
                    ]
                    try:
                        text = self.processor.apply_chat_template(
                            messages,
                            tokenize=False,
                            add_generation_prompt=True,
                            enable_thinking=False,
                        )
                    except TypeError:
                        text = self.processor.apply_chat_template(
                            messages,
                            tokenize=False,
                            add_generation_prompt=True,
                        )
                else:
                    text = full_prompt
            except Exception:
                text = full_prompt

            if self.model_type == 'image-text' and image_path:
                from PIL import Image
                with Image.open(image_path) as pil_img:
                    img = pil_img.convert('RGB')
                    inputs = self.processor(text=text, images=[img], return_tensors='pt')
            else:
                inputs = self.processor(text=text, return_tensors='pt')

            # move tensors to model device if possible
            try:
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            except Exception:
                pass

            # compute input length for slicing
            input_len = None
            try:
                if 'input_ids' in inputs:
                    input_len = inputs['input_ids'].shape[-1]
                elif 'input_ids' in locals():
                    input_len = locals()['input_ids'].shape[-1]
            except Exception:
                input_len = None

            try:
                gen_kwargs = {
                    "max_new_tokens": max_new_tokens,
                    "do_sample": False,
                    "num_beams": 1,
                    "use_cache": True,
                }
                tok = getattr(self.processor, 'tokenizer', None)
                if tok is not None:
                    pad_id = getattr(tok, 'pad_token_id', None)
                    eos_id = getattr(tok, 'eos_token_id', None)
                    if pad_id is not None:
                        gen_kwargs['pad_token_id'] = pad_id
                    if eos_id is not None:
                        gen_kwargs['eos_token_id'] = eos_id

                with torch.inference_mode():
                    outputs = self.model.generate(
                        **inputs,
                        **gen_kwargs,
                    )
            except Exception:
                with torch.no_grad():
                    outputs = self.model.generate(
                        **inputs,
                        **gen_kwargs,
                    )

            # decode and slice off prompt tokens if input_len known
            try:
                seq = outputs[0]
                if input_len is not None:
                    gen_seq = seq[input_len:]
                else:
                    gen_seq = seq
                if hasattr(self.processor, 'decode'):
                    resp = self.processor.decode(gen_seq, skip_special_tokens=True)
                else:
                    from transformers import AutoTokenizer
                    tok = AutoTokenizer.from_pretrained(self.model.config._name_or_path)
                    resp = tok.decode(gen_seq, skip_special_tokens=True)
            except Exception:
                resp = str(outputs)
            return resp
        except Exception as e:
            raise GemmaError(e)

        # NOTE: unreachable
