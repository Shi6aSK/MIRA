import io
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext

import requests
from PIL import Image, ImageTk

try:
    import serial
    import serial.tools.list_ports
    SERIAL_OK = hasattr(serial, "Serial")
    SERIAL_ERR = ""
except Exception as exc:
    serial = None
    SERIAL_OK = False
    SERIAL_ERR = str(exc)


class VisionGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32S3 Vision GUI")

        self.base_url = tk.StringVar(value="http://192.168.4.1")
        self.serial_port = tk.StringVar(value="")
        self.baud_rate = tk.StringVar(value="115200")
        self.use_serial = tk.BooleanVar(value=True)

        self.serial_conn = None
        self.running = False
        self.video_running = False
        self.status_running = False
        self.frame_count = 0

        self.frame_label = ttk.Label(root)
        self.status_label = ttk.Label(root, text="Status: idle")
        self.video_status_label = ttk.Label(root, text="Video: idle")

        self.log_box = scrolledtext.ScrolledText(root, width=80, height=10, state="disabled")
        self.command_entry = ttk.Entry(root)

        self._build_ui()
        self._refresh_ports()
        if not SERIAL_OK:
            self.log("PySerial is not available. Run:")
            self.log("  python -m pip uninstall -y serial")
            self.log("  python -m pip install pyserial")
            if SERIAL_ERR:
                self.log(f"Import error: {SERIAL_ERR}")

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="HTTP Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.base_url, width=28).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(top, text="Serial Port").grid(row=0, column=2, sticky="w")
        self.port_combo = ttk.Combobox(top, textvariable=self.serial_port, width=16)
        self.port_combo.grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(top, text="Refresh", command=self._refresh_ports).grid(row=0, column=4, padx=4)

        ttk.Label(top, text="Baud").grid(row=0, column=5, sticky="w")
        ttk.Entry(top, textvariable=self.baud_rate, width=8).grid(row=0, column=6, sticky="w", padx=4)

        ttk.Checkbutton(top, text="Use Serial", variable=self.use_serial).grid(row=0, column=7, sticky="w", padx=4)

        ttk.Button(top, text="Connect", command=self.connect).grid(row=0, column=8, padx=6)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=9, padx=4)
        ttk.Button(top, text="Test Frame", command=self.show_test_frame).grid(row=0, column=10, padx=4)

        video_frame = ttk.Frame(self.root)
        video_frame.pack(fill="both", expand=True, padx=8, pady=6)

        self.frame_label.pack(in_=video_frame, fill="both", expand=True)
        self.status_label.pack(in_=video_frame, fill="x")
        self.video_status_label.pack(in_=video_frame, fill="x")

        cmd_frame = ttk.Frame(self.root)
        cmd_frame.pack(fill="x", padx=8, pady=6)

        ttk.Label(cmd_frame, text="Command").pack(side="left")
        self.command_entry.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(cmd_frame, text="Send", command=self.send_command).pack(side="left")

        self.log_box.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    def _refresh_ports(self):
        if not SERIAL_OK:
            self.port_combo["values"] = []
            return
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.serial_port.get():
            self.serial_port.set(ports[0])

    def log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def connect(self):
        if self.running:
            return
        if self.use_serial.get() and not SERIAL_OK:
            self.log("PySerial is not available. Run:")
            self.log("  python -m pip uninstall -y serial")
            self.log("  python -m pip install pyserial")
            return

        if self.use_serial.get():
            try:
                self.serial_conn = serial.Serial(self.serial_port.get(), int(self.baud_rate.get()), timeout=0.1)
            except Exception as exc:
                self.log(f"Serial error: {exc}")
                return

        self.running = True
        self.video_running = True
        self.status_running = True
        self.log("Connected")
        self.video_status_label.config(text="Video: starting...")

        threading.Thread(target=self._serial_reader, daemon=True).start()
        threading.Thread(target=self._video_loop, daemon=True).start()
        threading.Thread(target=self._status_loop, daemon=True).start()

    def disconnect(self):
        self.running = False
        self.video_running = False
        self.status_running = False
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None
        self.log("Disconnected")

    def send_command(self):
        cmd = self.command_entry.get().strip()
        if not cmd:
            return
        if self.serial_conn:
            try:
                self.serial_conn.write((cmd + "\n").encode("utf-8"))
            except Exception as exc:
                self.log(f"Send error: {exc}")
        self.log(f"> {cmd}")
        self.command_entry.delete(0, "end")

    def _serial_reader(self):
        while self.running:
            if not self.serial_conn:
                time.sleep(0.1)
                continue
            try:
                line = self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                line = ""
            if line:
                self.log(line)

    def _video_loop(self):
        while self.video_running:
            url = self.base_url.get().rstrip("/") + "/raw"
            try:
                resp = requests.get(url, timeout=1)
                resp.raise_for_status()
                w = int(resp.headers.get("X-Width", "160"))
                h = int(resp.headers.get("X-Height", "120"))
                payload = resp.content
                self.root.after(0, self._update_frame, payload, w, h)
            except Exception as exc:
                self.root.after(0, self.video_status_label.config, {"text": f"Video: error {exc}"})
                time.sleep(0.5)
            time.sleep(0.05)

    def _status_loop(self):
        while self.status_running:
            url = self.base_url.get().rstrip("/") + "/status"
            try:
                resp = requests.get(url, timeout=1)
                resp.raise_for_status()
                data = resp.json()
                text = (
                    f"Status: obj={data.get('object_present')} side={data.get('side')} "
                    f"bbox={data.get('bbox')} frame={data.get('frame_id')}"
                )
                self.root.after(0, self.status_label.config, {"text": text})
            except Exception:
                pass
            time.sleep(0.5)

    def _update_frame(self, payload, w, h):
        try:
            expected = w * h
            if len(payload) != expected:
                self.video_status_label.config(text=f"Video: size mismatch {len(payload)} != {expected}")
                return
            image = Image.frombytes("L", (w, h), payload)
            image = image.resize((480, 360))
            tk_image = ImageTk.PhotoImage(image)
            self.frame_label.configure(image=tk_image)
            self.frame_label.image = tk_image
            self.frame_count += 1
            self.video_status_label.config(text=f"Video: frames={self.frame_count} {w}x{h}")
        except Exception as exc:
            self.video_status_label.config(text=f"Video: render error {exc}")

    def show_test_frame(self):
        path = os.path.join(os.path.dirname(__file__), "last_frame.png")
        if not os.path.exists(path):
            self.log("Test frame not found. Run: python tools/vision_gui.py after generating last_frame.png")
            return
        try:
            image = Image.open(path).convert("L").resize((480, 360))
            tk_image = ImageTk.PhotoImage(image)
            self.frame_label.configure(image=tk_image)
            self.frame_label.image = tk_image
            self.video_status_label.config(text="Video: showing test frame")
        except Exception as exc:
            self.video_status_label.config(text=f"Video: test frame error {exc}")


def main():
    root = tk.Tk()
    app = VisionGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.disconnect)
    root.mainloop()


if __name__ == "__main__":
    main()
