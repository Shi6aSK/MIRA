#!/usr/bin/env python3
"""
Serial Stream Viewer

Reads framed images and logs from a serial port and displays the live stream in a GUI.
Supports two frame modes:
 - JPEG frames framed as: "FRAME <len>\n" followed by <len> bytes of JPEG data
 - RAW RGB565 frames framed as: "FRAME RAW <width> <height> <len>\n" followed by <len> bytes (width*height*2)

Dependencies: pyserial, pillow, PyQt5
Install: pip install pyserial pillow PyQt5

Run: python tools/serial_viewer.py

"""
import sys
import threading
import struct
import io
import time
import json
import os
import queue
from collections import deque

# Force Qt to use software rendering to avoid GPU/OpenGL driver conflicts
# that can cause DLL init failures when importing torch in the same process.
# These must be set before importing PyQt5.
os.environ.setdefault('QT_OPENGL', 'software')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
from PyQt5 import QtWidgets, QtGui, QtCore
try:
    import serial
except Exception:
    serial = None
from PIL import Image
import subprocess

# Optional Gemma LLM runner. Defer importing heavy deps until runtime so GUI still starts
# even when PyTorch / NumPy mismatches exist. We'll attempt imports later when initializing LLM.
HAS_TORCH = False
GemmaRunner = None
GemmaError = Exception

DEFAULT_IMAGE_PROMPT = 'Describe the image briefly.'
DEFAULT_AUDIO_PROMPT = 'Transcribe the audio and respond briefly.'
DEFAULT_TEXT_PROMPT = 'Respond briefly.'


# No mock fallback: GUI requires real Gemma (local) or HF inference API. Mock runner removed.


class LogEmitter(QtCore.QObject):
    log_signal = QtCore.pyqtSignal(str)


class SerialReader(threading.Thread):
    def __init__(self, port, baud, mode, width, height, frame_queue, det_queue, log_callback):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.mode = mode
        self.width = width
        self.height = height
        self.frame_queue = frame_queue
        self.det_queue = det_queue
        self.log = log_callback
        self._running = threading.Event()
        self._running.set()
        self.ser = None
        self._write_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = {
            'bytes': 0,
            'frames': 0,
            'headers': 0,
            'errors': 0,
            'last_frame_ts': 0.0,
        }
        self._verbose = False

    def stop(self):
        self._running.clear()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def open_serial(self):
        # Check that pyserial provides Serial
        if serial is None or not hasattr(serial, 'Serial'):
            # Provide actionable instructions including the Python executable in use
            py = sys.executable or 'python'
            self.log("Serial open error: 'pyserial' not found or wrong 'serial' package installed.")
            self.log(f"Install into this Python: {py} -m pip install pyserial")
            self.log("If you have a different 'serial' package installed, run: pip uninstall serial && pip install pyserial")
            return False
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            try:
                self.ser.setDTR(False)
                self.ser.setRTS(False)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception:
                pass
            self.log(f"Opened {self.port} @ {self.baud}")
            return True
        except Exception as e:
            self.log(f"Serial open error: {e}")
            self.log("If this is a permission/port-in-use issue, ensure no other app (e.g., idf_monitor) is holding the COM port.")
            return False

    def send_line(self, line):
        if not line:
            return False
        try:
            if self.ser and self.ser.is_open:
                with self._write_lock:
                    self.ser.write((line + "\n").encode('utf-8'))
                return True
        except Exception as e:
            self.log(f"Serial write error: {e}")
        return False

    def set_verbose(self, enable):
        self._verbose = bool(enable)

    def get_stats(self):
        with self._stats_lock:
            return dict(self._stats)

    def _bump_stat(self, key, inc=1):
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + inc

    def _set_stat(self, key, value):
        with self._stats_lock:
            self._stats[key] = value

    def run(self):
        if not self.open_serial():
            return
        buf = bytearray()
        last_frame_ts = time.time()
        while self._running.is_set():
            try:
                chunk = self.ser.read(2048)
                if not chunk:
                    # periodic hint if no frames are seen
                    if time.time() - last_frame_ts > 6:
                        self.log('No frames yet; check COM port and baud match the ESP stream.')
                        last_frame_ts = time.time()
                    continue
                self._bump_stat('bytes', len(chunk))
                buf.extend(chunk)
                while True:
                    nl = buf.find(b'\n')
                    if nl == -1:
                        # prevent unbounded growth if we lost sync
                        if len(buf) > 8192:
                            del buf[:-1024]
                        break
                    line = bytes(buf[:nl + 1])
                    del buf[:nl + 1]
                    try:
                        s = line.decode('utf-8', errors='ignore').strip()
                    except Exception:
                        s = ''
                    if s.startswith('FRAME '):
                        self._bump_stat('headers', 1)
                        if self._verbose:
                            self.log(f"HDR {s}")
                        parts = s.split()
                        if len(parts) >= 2 and parts[1] == 'RAW':
                            # FRAME RAW <w> <h> <len>
                            if len(parts) >= 5:
                                try:
                                    w = int(parts[2]); h = int(parts[3]); l = int(parts[4])
                                except Exception:
                                    self._bump_stat('errors', 1)
                                    self.log(f"Malformed RAW header: {s}")
                                    continue
                                data = self._read_exact_from_buffer(l, buf)
                                if data is None:
                                    self._bump_stat('errors', 1)
                                    self.log('Timeout reading RAW frame')
                                    continue
                                img = self._rgb565_to_image(data, w, h)
                                if img:
                                    self.frame_queue.append(img)
                                    last_frame_ts = time.time()
                                    self._bump_stat('frames', 1)
                                    self._set_stat('last_frame_ts', last_frame_ts)
                        elif len(parts) >= 2 and parts[1] in ('RAW_GRAY', 'RAWG', 'GRAY'):
                            # FRAME RAW_GRAY <w> <h> <len>
                            if len(parts) >= 5:
                                try:
                                    w = int(parts[2]); h = int(parts[3]); l = int(parts[4])
                                except Exception:
                                    self._bump_stat('errors', 1)
                                    self.log(f"Malformed RAW_GRAY header: {s}")
                                    continue
                                data = self._read_exact_from_buffer(l, buf)
                                if data is None:
                                    self._bump_stat('errors', 1)
                                    self.log('Timeout reading RAW_GRAY frame')
                                    continue
                                img = self._gray_to_image(data, w, h)
                                if img:
                                    self.frame_queue.append(img)
                                    last_frame_ts = time.time()
                                    self._bump_stat('frames', 1)
                                    self._set_stat('last_frame_ts', last_frame_ts)
                        else:
                            # FRAME <len>
                            try:
                                l = int(parts[1])
                            except Exception:
                                self._bump_stat('errors', 1)
                                self.log(f"Malformed FRAME header: {s}")
                                continue
                            data = self._read_exact_from_buffer(l, buf)
                            if data is None:
                                self._bump_stat('errors', 1)
                                self.log('Timeout reading JPEG frame')
                                continue
                            try:
                                img = Image.open(io.BytesIO(data)).convert('RGB')
                                self.frame_queue.append(img)
                                last_frame_ts = time.time()
                                self._bump_stat('frames', 1)
                                self._set_stat('last_frame_ts', last_frame_ts)
                            except Exception as e:
                                self._bump_stat('errors', 1)
                                self.log(f"JPEG decode error: {e}")
                    else:
                        # treat as log line
                        if s:
                            if s.startswith('DETECT '):
                                try:
                                    payload = s[len('DETECT '):].strip()
                                    det = json.loads(payload)
                                    if self.det_queue is not None:
                                        self.det_queue.append(det)
                                except Exception:
                                    pass
                            self.log(s)
            except Exception as e:
                self.log(f"Serial read error: {e}")
                time.sleep(0.1)
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def _read_exact(self, n):
        out = bytearray()
        start = time.time()
        while len(out) < n and self._running.is_set():
            chunk = self.ser.read(n - len(out))
            if not chunk:
                # timeout
                if time.time() - start > 5.0:
                    return None
                continue
            out.extend(chunk)
        return bytes(out)

    def _read_exact_from_buffer(self, n, buf):
        out = bytearray()
        if buf:
            take = n if len(buf) >= n else len(buf)
            out.extend(buf[:take])
            del buf[:take]
        start = time.time()
        while len(out) < n and self._running.is_set():
            chunk = self.ser.read(n - len(out))
            if not chunk:
                if time.time() - start > 5.0:
                    return None
                continue
            out.extend(chunk)
        return bytes(out)

    def _rgb565_to_image(self, data, w, h):
        try:
            # data length should be w*h*2
            expected = w * h * 2
            if len(data) < expected:
                self.log(f"RAW data too short: {len(data)} < {expected}")
                return None
            # Convert to RGB bytes
            rgb = bytearray(w * h * 3)
            di = 0
            for i in range(0, expected, 2):
                pix = data[i] | (data[i+1] << 8)
                r = ((pix >> 11) & 0x1F) << 3
                g = ((pix >> 5) & 0x3F) << 2
                b = (pix & 0x1F) << 3
                rgb[di] = r; rgb[di+1] = g; rgb[di+2] = b
                di += 3
            img = Image.frombytes('RGB', (w, h), bytes(rgb))
            return img
        except Exception as e:
            self.log(f"RGB565 decode error: {e}")
            return None

    def _gray_to_image(self, data, w, h):
        try:
            expected = w * h
            if len(data) < expected:
                self.log(f"GRAY data too short: {len(data)} < {expected}")
                return None
            img = Image.frombytes('L', (w, h), bytes(data[:expected]))
            return img.convert('RGB')
        except Exception as e:
            self.log(f"GRAY decode error: {e}")
            return None


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ESP Serial Viewer')
        self.resize(800, 600)

        self.frame_queue = deque(maxlen=4)
        self.det_queue = deque(maxlen=8)
        self.reader = None
        self.last_frame = None
        self.last_action_time = 0.0
        self.last_action_gesture = ''
        self.recording = False

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        ctl_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(ctl_layout)

        self.port_edit = QtWidgets.QLineEdit('COM5')
        self.baud_combo = QtWidgets.QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(['115200', '230400', '460800', '921600', '1500000', '2000000'])
        self.baud_combo.setCurrentText('115200')
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(['RAW_GRAY', 'JPEG', 'RAW_RGB565'])
        self.w_edit = QtWidgets.QLineEdit('320')
        self.h_edit = QtWidgets.QLineEdit('240')
        self.stream_check = QtWidgets.QCheckBox('Stream')
        self.stream_check.setChecked(True)
        self.stream_check.toggled.connect(self.on_stream_toggle)
        self.verbose_check = QtWidgets.QCheckBox('Verbose stream')
        self.verbose_check.toggled.connect(self.on_verbose_toggle)
        self.connect_btn = QtWidgets.QPushButton('Connect')
        self.connect_btn.clicked.connect(self.toggle_connect)

        ctl_layout.addWidget(QtWidgets.QLabel('Port'))
        ctl_layout.addWidget(self.port_edit)
        ctl_layout.addWidget(QtWidgets.QLabel('Baud'))
        ctl_layout.addWidget(self.baud_combo)
        ctl_layout.addWidget(QtWidgets.QLabel('Mode'))
        ctl_layout.addWidget(self.mode_combo)
        ctl_layout.addWidget(QtWidgets.QLabel('W'))
        ctl_layout.addWidget(self.w_edit)
        ctl_layout.addWidget(QtWidgets.QLabel('H'))
        ctl_layout.addWidget(self.h_edit)
        ctl_layout.addWidget(self.stream_check)
        ctl_layout.addWidget(self.verbose_check)
        ctl_layout.addWidget(self.connect_btn)

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 480)
        layout.addWidget(self.image_label, stretch=1)

        self.det_label = QtWidgets.QLabel('Det: none')
        layout.addWidget(self.det_label)

        self.stream_stats = QtWidgets.QLabel('Stream: idle')
        layout.addWidget(self.stream_stats)

        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(150)
        layout.addWidget(self.log_view)

        cmd_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(cmd_layout)
        self.cmd_input = QtWidgets.QLineEdit()
        self.cmd_send = QtWidgets.QPushButton('Send Cmd')
        self.cmd_send.clicked.connect(self.on_send_cmd)
        cmd_layout.addWidget(QtWidgets.QLabel('UART Cmd'))
        cmd_layout.addWidget(self.cmd_input)
        cmd_layout.addWidget(self.cmd_send)

        self.log_emitter = LogEmitter()
        self.log_emitter.log_signal.connect(self._append_log)

        # LLM / control panel
        llm_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(llm_layout)
        self.llm_status = QtWidgets.QLabel('LLM: none')
        self.llm_input = QtWidgets.QLineEdit()
        self.llm_send = QtWidgets.QPushButton('Send to LLM')
        self.llm_send.clicked.connect(self.on_llm_send)
        self.capture_btn = QtWidgets.QPushButton('Capture Frame')
        self.capture_btn.clicked.connect(self.on_capture_frame)
        self.record_btn = QtWidgets.QPushButton('Record Audio')
        self.record_btn.clicked.connect(self.on_record_audio)
        self.auto_actions_check = QtWidgets.QCheckBox('Auto actions')
        self.auto_actions_check.setChecked(True)
        self.tts_check = QtWidgets.QCheckBox('Speak response')
        self.tts_check.setChecked(True)

        llm_layout.addWidget(self.llm_status)
        llm_layout.addWidget(self.llm_input)
        llm_layout.addWidget(self.llm_send)
        # Reload model button
        self.llm_reload = QtWidgets.QPushButton('Reload LLM')
        self.llm_reload.clicked.connect(self.reload_gemma)
        llm_layout.addWidget(self.llm_reload)
        # Image/audio selection widgets
        self.image_select = QtWidgets.QPushButton('Select Image')
        self.image_select.clicked.connect(self.select_image)
        self.selected_image_label = QtWidgets.QLabel('No image')
        self.audio_select = QtWidgets.QPushButton('Select Audio')
        self.audio_select.clicked.connect(self.select_audio)
        self.selected_audio_label = QtWidgets.QLabel('No audio')
        llm_layout.addWidget(self.image_select)
        llm_layout.addWidget(self.selected_image_label)
        llm_layout.addWidget(self.audio_select)
        llm_layout.addWidget(self.selected_audio_label)
        llm_layout.addWidget(self.capture_btn)
        llm_layout.addWidget(self.record_btn)
        llm_layout.addWidget(self.tts_check)
        llm_layout.addWidget(self.auto_actions_check)

        # Auto-send config: when the real Gemma runner becomes ready, auto-send this prompt
        self._auto_send_on_ready = True
        self._auto_sent = False
        self._llm_busy = False

        # Initialize Gemma interface (local model folder 'gemma')
        self.gemma = None
        try:
            from gemma_interface import GemmaInterface, GemmaError
            model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'gemma'))
            try:
                self.gemma = GemmaInterface(model_path=model_dir)
                self.llm_status.setText('LLM: loading')
                self.log(f'GemmaInterface instantiated, loading model from: {model_dir}')
                QtCore.QTimer.singleShot(200, self._poll_gemma_ready)
            except Exception as e:
                self.log(f'Failed to create GemmaInterface: {e}')
                self.gemma = None
        except Exception as e:
            self.log(f'GemmaInterface import failed: {e}')

        # If Gemma failed to load in-process due to DLL init errors (common with Qt),
        # spawn an isolated subprocess that loads the model instead and communicates
        # via stdin/stdout JSON lines. This mirrors the successful headless runner.
        self.gemma_subproc = None
        self.gemma_subproc_ready = False
        self.gemma_subproc_queue = queue.Queue()

        if not self.gemma:
            self.gemma = None
            self.llm_status.setText('LLM: unavailable')
            self.log('LLM unavailable: ensure PyTorch is installed in the venv and a local model exists in gemma/.')
            self.log('Or set HUGGINGFACEHUB_API_TOKEN to use the HF Inference API:')
            self.log('  setx HUGGINGFACEHUB_API_TOKEN "hf_..." (then restart your shell)')
            # Try to start subprocess runner as a fallback to isolate torch imports.
            try:
                self._start_gemma_subprocess()
            except Exception as e:
                self.log(f'Failed to start Gemma subprocess: {e}')

        # Log which Python executable is running and warn if not using the project venv
        try:
            py = sys.executable
            self.log(f'Python executable: {py}')
            # Simple heuristic: expect .venv in path for this workspace
            if '.venv' not in py.replace('\\', '/').lower():
                self.log('WARNING: You are not running the GUI with the workspace virtualenv.');
                self.log('Run with: .venv\\Scripts\\python.exe -u tools/serial_viewer.py')
        except Exception:
            pass

        self.timer = QtCore.QTimer()
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start()

        self.stats_timer = QtCore.QTimer()
        self.stats_timer.setInterval(500)
        self.stats_timer.timeout.connect(self.update_stream_stats)
        self.stats_timer.start()

        self.last_fps_time = time.time()
        self.frames = 0
        # selected media paths
        self.selected_image_path = None
        self.selected_audio_path = None

    def log(self, s):
        ts = time.strftime('%H:%M:%S')
        msg = f"[{ts}] {s}"
        if hasattr(self, 'log_emitter'):
            self.log_emitter.log_signal.emit(msg)
        else:
            self.log_view.append(msg)

    def _append_log(self, msg):
        self.log_view.append(msg)

    def update_stream_stats(self):
        if not self.reader:
            self.stream_stats.setText('Stream: idle')
            return
        stats = self.reader.get_stats()
        last_ts = stats.get('last_frame_ts', 0.0) or 0.0
        age = time.time() - last_ts if last_ts > 0 else -1.0
        if age < 0:
            age_text = 'never'
        else:
            age_text = f"{age:.1f}s"
        self.stream_stats.setText(
            f"Stream: bytes={stats.get('bytes', 0)} frames={stats.get('frames', 0)} "
            f"headers={stats.get('headers', 0)} errors={stats.get('errors', 0)} last={age_text}"
        )

    def on_verbose_toggle(self, enabled):
        if self.reader:
            self.reader.set_verbose(enabled)

    def toggle_connect(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
            self.connect_btn.setText('Connect')
            self.log('Disconnected')
            return
        port = self.port_edit.text().strip()
        try:
            baud = int(self.baud_combo.currentText().strip())
        except Exception:
            baud = 115200
        mode = self.mode_combo.currentText()
        try:
            w = int(self.w_edit.text())
            h = int(self.h_edit.text())
        except Exception:
            w, h = 320, 240
        self.reader = SerialReader(port, baud, mode, w, h, self.frame_queue, self.det_queue, self.log)
        self.reader.set_verbose(self.verbose_check.isChecked())
        self.reader.start()
        self.connect_btn.setText('Disconnect')
        self.log('Connecting...')
        QtCore.QTimer.singleShot(200, self._send_stream_mode)

    def _send_stream_mode(self):
        if not self.reader:
            return
        cmd = 'stream_on' if self.stream_check.isChecked() else 'stream_off'
        if self.reader.send_line(cmd):
            self.log(f"> {cmd}")

    def on_stream_toggle(self, enabled):
        if not self.reader:
            return
        cmd = 'stream_on' if enabled else 'stream_off'
        if self.reader.send_line(cmd):
            self.log(f"> {cmd}")

    def on_send_cmd(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        if not self.reader:
            self.log('Serial not connected')
            return
        if self.reader.send_line(cmd):
            self.log(f"> {cmd}")
        else:
            self.log('Failed to send command')
        self.cmd_input.clear()

    def update_frame(self):
        if not self.frame_queue:
            return
        img = self.frame_queue.popleft()
        self.last_frame = img
        # convert PIL Image to QImage
        data = img.tobytes('raw', 'RGB')
        qimg = QtGui.QImage(data, img.width, img.height, img.width * 3, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(qimg).scaled(self.image_label.width(), self.image_label.height(), QtCore.Qt.KeepAspectRatio)
        self.image_label.setPixmap(pix)
        self._process_detection()
        # fps
        self.frames += 1
        if time.time() - self.last_fps_time >= 1.0:
            self.log(f"FPS: {self.frames}")
            self.frames = 0
            self.last_fps_time = time.time()

    def _process_detection(self):
        if not self.det_queue:
            return
        det = self.det_queue.pop()
        try:
            kind = det.get('kind', 'none')
            side = det.get('side', 'none')
            gesture = det.get('gesture', 'none')
            iou = det.get('iou', 0.0)
            self.det_label.setText(f"Det: {kind} ({side}) gesture={gesture} iou={iou:.2f}")
            self._maybe_trigger_action(det)
        except Exception:
            pass

    def _build_detection_prompt(self, det):
        """Build a context-aware Gemma prompt from a detection dict."""
        # User-supplied custom prompt always takes priority
        custom = self.llm_input.text().strip()
        if custom:
            return custom
        kind = det.get('kind', 'none')
        gesture = det.get('gesture', 'none')
        side = det.get('side', 'center')
        if kind == 'face':
            g = str(gesture).strip().lower()
            if g in ('open_palm', 'palm'):
                return (
                    "You are a helpful robot assistant for a visually impaired user. "
                    "An open-palm gesture activated voice mode. "
                    "Use the attached audio and answer clearly in one or two short sentences."
                )
            if g in ('point', 'pointing'):
                return (
                    "You are assisting a visually impaired user. "
                    "Look at the attached frame and answer this question: "
                    "what is the object being pointed at? "
                    "Respond in one concise sentence."
                )
            return (
                f"You are a friendly robot assistant. "
                f"A face is visible on the {side} side. Respond briefly."
            )
        return DEFAULT_TEXT_PROMPT

    def _maybe_trigger_action(self, det):
        """Trigger Gemma or capture/record based on the latest detection."""
        if not self.auto_actions_check.isChecked():
            return
        kind = det.get('kind', 'none')
        gesture = det.get('gesture', 'none')
        if kind == 'none':
            return
        now = time.time()
        trigger_key = f"face:{gesture}"
        # Debounce: same event within 5 s is ignored
        if trigger_key == self.last_action_gesture and (now - self.last_action_time) < 5.0:
            return

        # New flow: face is the gate; gestures are interpreted only while a face is present.
        if kind != 'face':
            return

        g = str(gesture).strip().lower()
        if g in ('open_palm', 'palm'):
            self.last_action_gesture = trigger_key
            self.last_action_time = now
            self.on_record_audio(auto=True)
        elif g in ('point', 'pointing'):
            self.last_action_gesture = trigger_key
            self.last_action_time = now
            self.on_capture_frame(auto=True)

    def _poll_gemma_ready(self):
        if not self.gemma:
            return
        st = self.gemma.status()
        self.llm_status.setText(f'LLM: {st}')
        if st.startswith('error'):
            # Log detailed loader error if available and instruct next steps
            try:
                err = getattr(self.gemma, '_load_err', None)
                if err:
                    self.log('LLM loader error details:')
                    self.log(str(err))
            except Exception:
                pass
            self.llm_status.setText('LLM: error')
            self.log('LLM failed to load. Install CPU PyTorch wheel or set HUGGINGFACEHUB_API_TOKEN to use HF Inference API.')
            # attempt subprocess fallback when in-process loader errors
            try:
                self._start_gemma_subprocess()
            except Exception:
                pass
            return
        if st in ('loading',):
            QtCore.QTimer.singleShot(500, self._poll_gemma_ready)
            return
        # If ready (local) or inference-api and auto-send enabled, send a test 'hi' once
        if (st == 'ready' or st.startswith('inference-api')) and self._auto_send_on_ready and (not getattr(self, '_auto_sent', False)):
            self._auto_sent = True
            QtCore.QTimer.singleShot(100, self._auto_send_hi)

    def _gemma_status(self):
        """Return Gemma status string safely, handling missing/callable status."""
        try:
            if self.gemma is None:
                return ''
            s = self.gemma.status
            if callable(s):
                try:
                    return s() or ''
                except Exception:
                    return ''
            if isinstance(s, str):
                return s
        except Exception:
            pass
        return ''

    def _auto_prompt(self, kind):
        custom = self.llm_input.text().strip()
        if custom:
            return custom
        if kind == 'audio':
            return DEFAULT_AUDIO_PROMPT
        if kind == 'image':
            return DEFAULT_IMAGE_PROMPT
        return DEFAULT_TEXT_PROMPT

    def _speak_text(self, text):
        if not text:
            return
        try:
            import pyttsx3
        except Exception:
            self.log('pyttsx3 not installed; cannot speak response')
            return
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            self.log(f'TTS error: {e}')

    def _parse_json_from_line(self, line):
        """Try to extract a JSON object from a mixed stdout line."""
        if not line:
            return None
        line = line.strip()
        if not line:
            return None
        # Fast path: plain JSON line
        if line.startswith('{') and line.endswith('}'):
            try:
                return json.loads(line)
            except Exception:
                pass
        # Try to parse a JSON object embedded in the line
        first = line.find('{')
        last = line.rfind('}')
        if first != -1 and last != -1 and last > first:
            chunk = line[first:last + 1]
            try:
                return json.loads(chunk)
            except Exception:
                return None
        return None

    def _start_gemma_subprocess(self):
        # Start subprocess runner if not already started. Run reader in background
        if getattr(self, 'gemma_subproc', None):
            return
        try:
            runner = os.path.join(os.path.dirname(__file__), 'run_gemma_subprocess.py')
            py = sys.executable or 'python'
            cmd = [py, '-u', runner]
            self.log(f'Starting Gemma subprocess: {cmd}')
            self.gemma_subproc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1)
            self.gemma_subproc_ready = False

            def reader_thread():
                start = time.time()
                timeout = 300.0
                try:
                    while True:
                        line = self.gemma_subproc.stdout.readline()
                        if not line:
                            # check timeout
                            if time.time() - start > timeout:
                                self.log('Gemma subprocess reader timed out')
                                break
                            time.sleep(0.05)
                            continue
                        line = line.strip()
                        try:
                            obj = json.loads(line)
                        except Exception:
                            self.log(f'Gemma subprocess: {line}')
                            continue
                        self.log(f'Gemma subprocess evt: {obj.get("event") or obj.get("status") or obj.get("error")}')
                        status = obj.get('status') if 'status' in obj else None
                        status_text = str(status or '')
                        if (
                            status_text == 'ready'
                            or status_text.startswith('inference-api')
                            or (
                                isinstance(obj.get('event'), str)
                                and obj.get('event') == 'status'
                                and (
                                    str(obj.get('status', '')) == 'ready'
                                    or str(obj.get('status', '')).startswith('inference-api')
                                )
                            )
                        ):
                            self.gemma_subproc_ready = True
                            # update UI on main thread
                            def set_ready():
                                try:
                                    ready_mode = 'subprocess'
                                    if status_text.startswith('inference-api'):
                                        ready_mode = 'subprocess (hf api)'
                                    self.llm_status.setText(f'LLM: {ready_mode}')
                                    self.log('Gemma subprocess ready')
                                    if self._auto_send_on_ready and (not getattr(self, '_auto_sent', False)):
                                        self._auto_sent = True
                                        QtCore.QTimer.singleShot(100, self._auto_send_hi)
                                except Exception:
                                    pass
                            QtCore.QTimer.singleShot(0, set_ready)
                            break
                        if obj.get('event') == 'error' or str(obj.get('status', '')).startswith('error'):
                            break
                except Exception as e:
                    self.log(f'Gemma subprocess reader error: {e}')

            t = threading.Thread(target=reader_thread, daemon=True)
            t.start()
        except Exception as e:
            self.log(f'Failed to start Gemma subprocess: {e}')

    def reload_gemma(self):
        # Ask GemmaInterface to reload the model if supported
        try:
            if self.gemma and hasattr(self.gemma, 'reload'):
                self.gemma.reload()
                self.llm_status.setText('LLM: reloading')
                self.log('Reloading Gemma model...')
                QtCore.QTimer.singleShot(200, self._poll_gemma_ready)
            else:
                self.log('Reload not available: GemmaInterface not initialized or reload() not supported.')
        except Exception as e:
            self.log(f'Failed to reload Gemma: {e}')

    def _auto_send_hi(self):
        # Send 'hi' to the LLM in a background thread and display the result
        # If in-process Gemma is unavailable or in error state, but subprocess is ready,
        # allow auto-send to proceed via subprocess.
        if (not self.gemma or self._gemma_status().startswith('error')) and not getattr(self, 'gemma_subproc_ready', False):
            self.log('LLM not available for auto-send')
            return
        prompt = 'hi'
        self.log(f'Auto LLM prompt: {prompt}')
        # Reuse the common generator helper
        self._start_generate_thread(prompt, max_new_tokens=64, show_dialog=True)

    def on_llm_send(self):
        # Prevent duplicate/overlapping requests
        if getattr(self, '_llm_busy', False):
            self.log('LLM is busy; please wait for the previous response.')
            return
        # If in-process Gemma is available and healthy, use it immediately.
        if self.gemma and not self._gemma_status().startswith('error'):
            prompt = self.llm_input.text().strip()
            if not prompt:
                return
            self.log(f'LLM prompt: {prompt}')
            self._start_generate_thread(prompt, max_new_tokens=64, show_dialog=False)
            return

        # If subprocess runner exists but is still warming up, wait in background and send when ready
        if getattr(self, 'gemma_subproc', None) and not getattr(self, 'gemma_subproc_ready', False):
            prompt = self.llm_input.text().strip()
            if not prompt:
                return
            self.log('LLM subprocess warming up; will send when ready')
            def waiter():
                start = time.time()
                while time.time() - start < 120:
                    if getattr(self, 'gemma_subproc_ready', False):
                        self._start_generate_thread(prompt, max_new_tokens=64, show_dialog=False)
                        return
                    time.sleep(0.5)
                self.log('LLM subprocess did not become ready in time')
            threading.Thread(target=waiter, daemon=True).start()
            return

        # Otherwise, not available
        if not self.gemma and not getattr(self, 'gemma_subproc_ready', False):
            self.log('LLM not available')
            return
        # Fallback: send prompt (for cases gemma_subproc_ready is True)
        prompt = self.llm_input.text().strip()
        if not prompt:
            return
        self.log(f'LLM prompt: {prompt}')
        self._start_generate_thread(prompt, max_new_tokens=64, show_dialog=False)

    def _start_generate_thread(self, prompt, max_new_tokens=96, show_dialog=False, speak_response=None):
        """Start background thread to call GemmaInterface.generate and handle UI update."""
        # mark busy and ensure reset when complete
        if getattr(self, '_llm_busy', False):
            self.log('LLM is busy; ignoring duplicate request')
            return
        self._llm_busy = True

        if speak_response is None:
            try:
                do_speak = bool(self.tts_check.isChecked())
            except Exception:
                do_speak = False
        else:
            do_speak = speak_response

        if not self.gemma and not getattr(self, 'gemma_subproc', None):
            self.log('LLM interface missing')
            self._llm_busy = False
            return

        def _worker():
            try:
                # If we have an in-process Gemma instance, prefer that
                if self.gemma and not self._gemma_status().startswith('error'):
                    try:
                        out = self.gemma.generate(prompt, image_path=self.selected_image_path, audio_path=self.selected_audio_path, max_new_tokens=max_new_tokens)
                        self.log('LLM response:')
                        self.log(out)
                        if show_dialog:
                            def show():
                                try:
                                    QtWidgets.QMessageBox.information(self, 'LLM Response', out)
                                except Exception:
                                    pass
                            QtCore.QTimer.singleShot(0, show)
                        if do_speak:
                            self._speak_text(out)
                        return
                    except Exception as e:
                        self.log(f'LLM runtime error (in-process): {e}')

                # Otherwise, if we started a subprocess runner, send request via stdin/stdout
                if self.gemma_subproc:
                    try:
                        req_id = int(time.time() * 1000) % 1000000
                        req = {"id": req_id, "cmd": "generate", "prompt": prompt, "image": self.selected_image_path, "audio": self.selected_audio_path, "max_new_tokens": max_new_tokens}
                        line = json.dumps(req, ensure_ascii=False)
                        # send
                        try:
                            self.gemma_subproc.stdin.write(line + "\n")
                            self.gemma_subproc.stdin.flush()
                        except Exception as e:
                            self.log(f'Failed to write to Gemma subprocess stdin: {e}')
                            return
                        # read response lines until matching id
                        start = time.time()
                        while time.time() - start < 60:
                            out_line = self.gemma_subproc.stdout.readline()
                            if not out_line:
                                time.sleep(0.05)
                                continue
                            try:
                                obj = json.loads(out_line.strip())
                            except Exception:
                                continue
                            if obj.get('id') == req_id:
                                if obj.get('ok'):
                                    resp = obj.get('resp', '')
                                    self.log('LLM response (subproc):')
                                    self.log(resp)
                                    if show_dialog:
                                        def show():
                                            try:
                                                QtWidgets.QMessageBox.information(self, 'LLM Response', resp)
                                            except Exception:
                                                pass
                                        QtCore.QTimer.singleShot(0, show)
                                    if do_speak:
                                        self._speak_text(resp)
                                else:
                                    self.log(f'LLM subprocess error: {obj.get("error")}')
                                break
                        return
                    except Exception as e:
                        self.log(f'LLM runtime error (subproc): {e}')

                self.log('LLM not available')
            finally:
                # clear busy flag
                try:
                    self._llm_busy = False
                except Exception:
                    pass
        threading.Thread(target=_worker, daemon=True).start()

    def on_capture_frame(self, auto=False):
        # save last displayed frame (if any) to tools/captures
        if self.last_frame is None:
            self.log('No frame to capture')
            return
        img = self.last_frame
        import os
        d = os.path.join(os.path.dirname(__file__), '..', 'captures')
        os.makedirs(d, exist_ok=True)
        fname = os.path.join(d, f'capture_{int(time.time())}.jpg')
        try:
            img.save(fname, format='JPEG')
            self.selected_image_path = fname
            try:
                self.selected_image_label.setText(os.path.basename(fname))
            except Exception:
                pass
            msg = 'Captured frame' if auto else 'Captured frame'
            self.log(f'{msg} -> {fname}')
            if auto:
                prompt = (
                    "You are assisting a visually impaired user. "
                    "Look at the attached camera frame and answer this question: "
                    "what is the object being pointed at? "
                    "Respond in one short sentence."
                )
                self._start_generate_thread(prompt, max_new_tokens=72, show_dialog=False,
                                            speak_response=self.tts_check.isChecked())
        except Exception as e:
            self.log(f'Capture save error: {e}')

    def on_record_audio(self, auto=False):
        # record short audio snippet if sounddevice available
        if self.recording:
            return
        try:
            import sounddevice as sd
            import numpy as np
            import scipy.io.wavfile as wav
        except Exception:
            self.log('sounddevice/scipy not installed')
            self.log('Install with: pip install sounddevice scipy numpy')
            return
        self.recording = True
        self.log('Recording 3s...')
        def rec():
            try:
                fs = 16000
                rec = sd.rec(int(3 * fs), samplerate=fs, channels=1)
                sd.wait()
                data = (rec * 32767).astype('int16')
                import os
                d = os.path.join(os.path.dirname(__file__), '..', 'captures')
                os.makedirs(d, exist_ok=True)
                fname = os.path.join(d, f'audio_{int(time.time())}.wav')
                wav.write(fname, fs, data)
                self.log(f'Recorded audio -> {fname}')
                def _on_saved():
                    self.selected_audio_path = fname
                    try:
                        self.selected_audio_label.setText(os.path.basename(fname))
                    except Exception:
                        pass
                    if auto:
                        prompt = self._auto_prompt('audio')
                        self._start_generate_thread(prompt, max_new_tokens=72, show_dialog=False)
                QtCore.QTimer.singleShot(0, _on_saved)
            except Exception as e:
                self.log(f'Record error: {e}')
            finally:
                self.recording = False
        threading.Thread(target=rec, daemon=True).start()

    def select_image(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select image', os.getcwd(), 'Images (*.png *.jpg *.jpeg *.bmp)')
        if fname:
            self.selected_image_path = fname
            try:
                self.selected_image_label.setText(os.path.basename(fname))
            except Exception:
                pass

    def select_audio(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select audio', os.getcwd(), 'Audio (*.wav *.mp3 *.m4a)')
        if fname:
            self.selected_audio_path = fname
            try:
                self.selected_audio_label.setText(os.path.basename(fname))
            except Exception:
                pass


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
