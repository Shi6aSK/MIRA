#!/usr/bin/env python3
"""
ESP Vision Assistant
--------------------
Face-first interaction controller for the ESP32 vision pipeline.

Usage:
    python tools/assistant.py --host http://192.168.X.X

The ESP IP is printed on the ESP serial console at boot:
    W app: Open http://192.168.X.X/ in a browser

Requirements:
    pip install requests sounddevice scipy numpy
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

POLL_INTERVAL = 0.3
FACE_GATE_SEC = 2.0
COOLDOWN_SEC = 4.0
AUDIO_SECONDS = 3.0


# ── Gemma subprocess wrapper ──────────────────────────────────────────────────

class GemmaClient:
    """Drive run_gemma_subprocess.py using a request/response JSON protocol."""

    def __init__(self):
        script = os.path.join(os.path.dirname(__file__), "run_gemma_subprocess.py")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._req_id = 0
        self._ready = threading.Event()
        self._resp_cv = threading.Condition()
        self._responses: Dict[int, dict] = {}
        self._last_status = "starting"
        self._had_error = False
        self._closed = False

        threading.Thread(target=self._drain_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stdout(self):
        for line in self._proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                print(f"[gemma] {text}", flush=True)
                continue

            rid = obj.get("id")
            if rid is not None:
                with self._resp_cv:
                    self._responses[int(rid)] = obj
                    self._resp_cv.notify_all()
                continue

            event = obj.get("event")
            status = obj.get("status")
            if status:
                self._last_status = str(status)
            if event:
                print(f"[gemma] {event}: {status or obj}", flush=True)
            if status == "ready" or str(status).startswith("inference-api"):
                self._ready.set()
            if str(status).startswith("error") or event == "error":
                self._had_error = True
                self._ready.set()

    def _drain_stderr(self):
        for line in self._proc.stderr:
            print(f"[gemma] {line.rstrip()}", flush=True)

    def wait_ready(self, timeout=180):
        if not self._ready.wait(timeout):
            print("[gemma] WARNING: model may not be ready yet", flush=True)
        if self._had_error:
            print(f"[gemma] WARNING: loader reported error status: {self._last_status}", flush=True)

    def generate(self, prompt, image=None, audio=None, max_new_tokens=72, timeout=90):
        self._req_id += 1
        rid = self._req_id
        msg = json.dumps(
            {
                "id": rid,
                "cmd": "generate",
                "prompt": prompt,
                "image": image,
                "audio": audio,
                "max_new_tokens": int(max_new_tokens),
            }
        )
        try:
            if not self._proc.stdin:
                return "(error: subprocess stdin unavailable)"
            self._proc.stdin.write(msg + "\n")
            self._proc.stdin.flush()

            deadline = time.time() + timeout
            with self._resp_cv:
                while rid not in self._responses:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        return "(error: timeout waiting for Gemma response)"
                    self._resp_cv.wait(timeout=remaining)
                obj = self._responses.pop(rid)

            if obj.get("ok"):
                return obj.get("resp", "(empty)")
            return f"(error: {obj.get('error', 'unknown')})"
        except Exception as e:
            return f"(error: {e})"

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass


def fetch_frame_jpeg(session: requests.Session, stream_url: str, max_bytes: int = 350000) -> Optional[bytes]:
    """Read the first complete JPEG frame from the MJPEG stream endpoint."""
    try:
        with session.get(stream_url, stream=True, timeout=(3, 8)) as resp:
            resp.raise_for_status()
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    break
                start = buf.find(b"\xff\xd8")
                if start == -1:
                    continue
                end = buf.find(b"\xff\xd9", start + 2)
                if end != -1:
                    return bytes(buf[start : end + 2])
    except Exception as exc:
        print(f"[frame] capture error: {exc}", flush=True)
    return None


def save_capture_bytes(capture_dir: Path, prefix: str, ext: str, data: bytes) -> Path:
    capture_dir.mkdir(parents=True, exist_ok=True)
    out = capture_dir / f"{prefix}_{int(time.time())}{ext}"
    out.write_bytes(data)
    return out


def record_audio_snippet(capture_dir: Path, seconds: float) -> Tuple[Optional[Path], Optional[str]]:
    """Record a short mono WAV snippet; returns (path, error)."""
    try:
        import numpy as np
        import sounddevice as sd
        import scipy.io.wavfile as wav
    except Exception:
        return None, "sounddevice/scipy/numpy not available"

    sample_rate = 16000
    duration = max(0.5, float(seconds))
    samples = int(sample_rate * duration)
    try:
        rec = sd.rec(samples, samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        data = (rec[:, 0] * 32767.0).clip(-32768, 32767).astype("int16")
        capture_dir.mkdir(parents=True, exist_ok=True)
        out = capture_dir / f"audio_{int(time.time())}.wav"
        wav.write(str(out), sample_rate, data)
        return out, None
    except Exception as exc:
        return None, str(exc)


def print_detection(det: dict):
    kind = det.get("kind", "none")
    gesture = det.get("gesture", "none")
    side = det.get("side", "none")
    score = det.get("score", 0.0)
    frame_id = det.get("frame_id", -1)
    print(
        f"[detect] frame={frame_id} kind={kind} gesture={gesture} side={side} score={float(score):.3f}",
        flush=True,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ESP Vision Assistant (face-first flow)")
    parser.add_argument(
        "--host",
        default="http://192.168.1.1",
        help="ESP32 HTTP base URL e.g. http://192.168.0.42",
    )
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL)
    parser.add_argument("--face-gate", type=float, default=FACE_GATE_SEC)
    parser.add_argument("--cooldown", type=float, default=COOLDOWN_SEC)
    parser.add_argument("--audio-seconds", type=float, default=AUDIO_SECONDS)
    parser.add_argument("--max-tokens", type=int, default=72)
    parser.add_argument("--capture-dir", default=os.path.join("captures"))
    parser.add_argument("--no-gemma", action="store_true", help="Disable Gemma and print detections only")
    args = parser.parse_args()

    host = args.host.rstrip("/")
    detect_url = f"{host}/detect"
    stream_url = f"{host}/stream"
    capture_dir = Path(args.capture_dir)
    session = requests.Session()

    gemma = None
    if not args.no_gemma:
        print("Starting Gemma subprocess...", flush=True)
        gemma = GemmaClient()
        print("Waiting for model to load (may take 1-2 min)...", flush=True)
        gemma.wait_ready(timeout=180)
        _ = gemma.generate("Reply with exactly: ready", max_new_tokens=8, timeout=45)
        print("Gemma ready.\n", flush=True)

    print(f"Polling {detect_url} every {args.interval}s (Ctrl-C to stop)\n")

    face_gate_until = 0.0
    last_frame_id = -1
    last_action_ts: Dict[str, float] = {}
    action_busy = False
    action_lock = threading.Lock()

    def run_action(name: str, worker):
        nonlocal action_busy
        with action_lock:
            if action_busy:
                print(f"[action] busy; skipping {name}", flush=True)
                return
            action_busy = True

        def _job():
            nonlocal action_busy
            try:
                print(f"[action] {name}", flush=True)
                worker()
            finally:
                with action_lock:
                    action_busy = False

        threading.Thread(target=_job, daemon=True).start()

    try:
        while True:
            try:
                det = session.get(detect_url, timeout=3).json()
            except Exception as e:
                print(f"[error] {e}", flush=True)
                time.sleep(args.interval)
                continue

            now = time.time()
            kind = str(det.get("kind", "none")).lower()
            gesture = str(det.get("gesture", "none")).lower()
            frame_id = int(det.get("frame_id", -1))

            if frame_id != last_frame_id:
                print_detection(det)
                last_frame_id = frame_id

            # Face is the gate: gestures are honored only within this active window.
            if kind == "face":
                face_gate_until = now + max(0.5, float(args.face_gate))

            if not gemma:
                time.sleep(args.interval)
                continue

            if now > face_gate_until:
                time.sleep(args.interval)
                continue
            if kind != "face":
                time.sleep(args.interval)
                continue

            if gesture in ("open_palm", "palm"):
                action_key = "voice"
                if now - last_action_ts.get(action_key, 0.0) < float(args.cooldown):
                    time.sleep(args.interval)
                    continue
                last_action_ts[action_key] = now

                det_snapshot = dict(det)

                def _voice_worker():
                    audio_path, err = record_audio_snippet(capture_dir, args.audio_seconds)
                    if not audio_path:
                        print(f"[audio] capture failed: {err}", flush=True)
                        prompt = (
                            "You are a helpful robot assistant. "
                            "Voice mode was requested, but audio capture is unavailable. "
                            "Ask the user to retry briefly."
                        )
                        resp = gemma.generate(prompt, max_new_tokens=min(args.max_tokens, 56))
                        print(f"[gemma] {resp}\n", flush=True)
                        return

                    print(f"[audio] recorded: {audio_path}", flush=True)
                    prompt = (
                        "You are a helpful robot assistant for a visually impaired user. "
                        "An open-palm gesture activated voice mode. "
                        "Use the attached audio to answer the user's spoken request briefly and clearly."
                    )
                    resp = gemma.generate(
                        prompt,
                        audio=str(audio_path),
                        max_new_tokens=args.max_tokens,
                    )
                    print(f"[gemma] {resp}\n", flush=True)

                run_action(f"voice ({det_snapshot.get('side', 'center')})", _voice_worker)

            elif gesture in ("point", "pointing"):
                action_key = "object"
                if now - last_action_ts.get(action_key, 0.0) < float(args.cooldown):
                    time.sleep(args.interval)
                    continue
                last_action_ts[action_key] = now

                det_snapshot = dict(det)

                def _point_worker():
                    jpeg = fetch_frame_jpeg(session, stream_url)
                    if not jpeg:
                        print("[frame] capture failed", flush=True)
                        return
                    img_path = save_capture_bytes(capture_dir, "point", ".jpg", jpeg)
                    print(f"[frame] captured: {img_path}", flush=True)
                    prompt = (
                        "You are assisting a visually impaired user. "
                        "Look at the attached camera frame and answer this question: "
                        "what is the object being pointed at? "
                        "Respond in one short sentence."
                    )
                    resp = gemma.generate(
                        prompt,
                        image=str(img_path),
                        max_new_tokens=args.max_tokens,
                    )
                    print(f"[gemma] {resp}\n", flush=True)

                run_action(f"object-query ({det_snapshot.get('side', 'center')})", _point_worker)

            time.sleep(args.interval)
    finally:
        if gemma:
            gemma.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
