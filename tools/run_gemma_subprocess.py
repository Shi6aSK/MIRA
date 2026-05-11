"""Subprocess runner that loads GemmaInterface in an isolated process and serves generate requests via stdin/stdout.

Protocol: JSON lines on stdin, responses as JSON lines on stdout.
Request: {"id": <int>, "cmd": "generate", "prompt": "...", "image": "path"}
Response: {"id": <int>, "ok": true, "resp": "..."} or {"id": <int>, "ok": false, "error": "..."}
"""
import sys
import json
import os
import time

# Ensure stdout/stderr use UTF-8 to avoid Windows console encoding errors when
# emitting emoji or other non-ASCII characters.
try:
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    # Older Pythons or reconfigure not available, continue anyway.
    pass

from gemma_interface import GemmaInterface, GemmaError


def write(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'gemma'))
    gi = None
    try:
        gi = GemmaInterface(model_path=model_dir)
        write({"event": "started", "status": gi.status()})
    except Exception as e:
        write({"event": "error", "error": str(e)})
        return 1

    # wait until ready or error
    start = time.time()
    while True:
        st = gi.status()
        write({"event": "status", "status": st})
        if st == 'ready' or st.startswith('inference-api'):
            break
        if st.startswith('error'):
            write({"event": "error", "error": str(getattr(gi, '_load_err', None))})
            return 2
        time.sleep(0.5)

    # serve requests
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            write({"id": None, "ok": False, "error": f"json:{e}"})
            continue
        rid = req.get('id')
        cmd = req.get('cmd')
        if cmd == 'generate':
            prompt = req.get('prompt', '')
            image = req.get('image')
            audio = req.get('audio')
            max_new_tokens = req.get('max_new_tokens', 72)
            try:
                resp = gi.generate(prompt, image_path=image, audio_path=audio, max_new_tokens=max_new_tokens)
                write({"id": rid, "ok": True, "resp": resp})
            except Exception as e:
                write({"id": rid, "ok": False, "error": str(e)})
        elif cmd == 'ping':
            write({"id": rid, "ok": True, "resp": 'pong'})
        else:
            write({"id": rid, "ok": False, "error": f'unknown cmd: {cmd}'})


if __name__ == '__main__':
    sys.exit(main())
