#!/usr/bin/env python3
"""라즈봇 카메라 실시간 화면 + 값 조절 창 (노트북에서 실행).

SSH로 로봇에 접속해 화면을 받고, 슬라이더 값을 v4l2-ctl로 바로 넣는다.
로봇에 파일을 남기지 않고 포트도 열지 않는다. 바퀴 명령은 없다.

    python camera_tuner.py [--host raspbot-03.local]
"""
import argparse
import base64
import json
import queue
import struct
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

# 로봇에서 도는 부분. 화면을 보내고, 받은 값을 카메라에 넣는다.
ROBOT_CODE = r'''
import json, re, struct, subprocess, sys, threading, time
import cv2

DEVICE = "/dev/video0"
out = sys.stdout.buffer
out_lock = threading.Lock()
stop = threading.Event()


def send(kind, payload):
    with out_lock:
        out.write(struct.pack(">I", len(payload) + 1) + kind + payload)
        out.flush()


def send_json(obj):
    send(b"J", json.dumps(obj, ensure_ascii=False).encode())


def read_controls():
    text = subprocess.run(["v4l2-ctl", "-d", DEVICE, "--list-ctrls"],
                          capture_output=True, text=True).stdout
    controls = {}
    for line in text.splitlines():
        match = re.match(r"\s*(\w+) 0x\w+ \((\w+)\)\s*:(.*)", line)
        if not match:
            continue
        info = {"type": match.group(2)}
        for key, value in re.findall(r"(min|max|default|value)=(-?\d+)", match.group(3)):
            info[key] = int(value)
        controls[match.group(1)] = info
    return controls


def apply(name, value):
    result = subprocess.run(["v4l2-ctl", "-d", DEVICE, "-c", "%s=%d" % (name, value)],
                            capture_output=True, text=True)
    if result.returncode:
        send_json({"error": "%s=%d: %s" % (name, value, result.stderr.strip()[:120])})


def read_commands():
    for line in sys.stdin:
        command = json.loads(line)
        if command.get("quit"):
            break
        for name, value in command.get("set", []):
            apply(name, int(value))
        if command.get("read"):
            send_json({"controls": read_controls()})
    stop.set()


running = subprocess.run(["ps", "-C", "python3", "-o", "cmd="], capture_output=True, text=True).stdout
busy = [line for line in running.splitlines() if "missions/" in line]
if busy:
    send_json({"fatal": "다른 프로그램이 카메라를 쓰는 중입니다: " + busy[0][:60]})
    sys.exit(0)

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
if not cap.isOpened():
    send_json({"fatal": "카메라를 열지 못했습니다. USB 연결을 확인하세요."})
    sys.exit(0)

send_json({"controls": read_controls()})
threading.Thread(target=read_commands, daemon=True).start()

latest = None
latest_lock = threading.Lock()


def grab():
    global latest
    while not stop.is_set():
        ok, frame = cap.read()
        if ok:
            with latest_lock:
                latest = frame


threading.Thread(target=grab, daemon=True).start()
try:
    while not stop.is_set():
        started = time.monotonic()
        with latest_lock:
            frame = latest
        if frame is not None:
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                send(b"I", jpeg.tobytes())
        time.sleep(max(0.005, 0.08 - (time.monotonic() - started)))
except BrokenPipeError:
    pass
stop.set()
time.sleep(0.1)
cap.release()
'''

ROI_TOP, ROI_BOTTOM = 120, 300  # 07번이 노란 선을 찾는 줄 범위
YELLOW_DEFAULT = {"h_min": 15, "h_max": 40, "s_min": 80, "v_min": 100}  # 07번 기준

# (설정 이름, 화면 이름). 자동 켜기/끄기는 따로 둔다.
CAMERA_SLIDERS = [
    ("exposure_time_absolute", "노출"),
    ("white_balance_temperature", "색온도"),
    ("brightness", "밝기"),
    ("contrast", "대비"),
    ("saturation", "채도"),
    ("hue", "색조"),
    ("gamma", "감마"),
    ("gain", "게인"),
    ("backlight_compensation", "역광 보정"),
    ("sharpness", "선명도"),
]
AUTO_EXPOSURE_ON, AUTO_EXPOSURE_MANUAL = 3, 1


def measure(frame, yellow, top=ROI_TOP, bottom=ROI_BOTTOM):
    """07번과 같은 방식으로 지정한 줄 범위의 노란 점과 덩어리를 센다."""
    hsv = cv2.cvtColor(frame[top:bottom], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (yellow["h_min"], yellow["s_min"], yellow["v_min"]),
                       (yellow["h_max"], 255, 255))
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
    blobs = sorted(((float(centers[i, 0]), int(stats[i, cv2.CC_STAT_AREA]))
                    for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 50),
                   key=lambda blob: -blob[1])[:2]
    whole = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    washed = float(np.mean((whole[:, :, 1] < 40) & (whole[:, :, 2] >= 250))) * 100
    return dict(mask=mask, blobs=blobs, yellow=int(np.count_nonzero(mask)),
                brightness=float(frame.mean()), washed=washed)


def annotate(frame, result, show_mask, top=ROI_TOP, bottom=ROI_BOTTOM):
    shown = frame.copy()
    if show_mask:
        roi = shown[top:bottom]
        roi[result["mask"] > 0] = (0, 0, 255)
    cv2.line(shown, (0, top), (639, top), (0, 255, 0), 1)
    cv2.line(shown, (0, bottom - 1), (639, bottom - 1), (0, 255, 0), 1)
    for x, _ in result["blobs"]:
        cv2.line(shown, (int(x), top), (int(x), bottom - 1), (0, 255, 255), 2)
    return shown


def setting_order(values):
    """자동을 먼저 끄고 값을 넣은 뒤, 자동을 켤 거면 마지막에 켠다."""
    order = []
    for auto, manual_value, target in (("auto_exposure", AUTO_EXPOSURE_MANUAL, "exposure_time_absolute"),
                                       ("white_balance_automatic", 0, "white_balance_temperature")):
        if auto in values or target in values:
            order.append((auto, manual_value))
            if target in values:
                order.append((target, values[target]))
            if auto in values and values[auto] != manual_value:
                order.append((auto, values[auto]))
    order += [(name, value) for name, value in values.items()
              if name not in ("auto_exposure", "exposure_time_absolute",
                              "white_balance_automatic", "white_balance_temperature")]
    return order


class Link:
    """SSH 한 줄로 로봇과 주고받는다."""

    def __init__(self, host):
        code = base64.b64encode(ROBOT_CODE.encode()).decode()
        remote = "python3 -u -c 'import sys,base64;exec(base64.b64decode(sys.argv[1]))' " + code
        self.process = subprocess.Popen(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-o", "ServerAliveInterval=5", "pi@" + host, remote],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = queue.Queue()
        self.frame = None
        self.frame_lock = threading.Lock()
        self.frames_received = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read_exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.process.stdout.read(size - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    def _read(self):
        try:
            while True:
                length = struct.unpack(">I", self._read_exact(4))[0]
                payload = self._read_exact(length)
                if payload[:1] == b"I":
                    with self.frame_lock:
                        self.frame = payload[1:]
                        self.frames_received += 1
                else:
                    self.messages.put(json.loads(payload[1:].decode()))
        except (EOFError, OSError, ValueError):
            error = b""
            try:
                error = self.process.stderr.read() or b""
            except OSError:
                pass
            self.messages.put({"closed": error.decode(errors="replace").strip()[-200:]})

    def take_frame(self):
        with self.frame_lock:
            frame, self.frame = self.frame, None
        return frame

    def send(self, command):
        try:
            self.process.stdin.write((json.dumps(command) + "\n").encode())
            self.process.stdin.flush()
        except OSError:
            pass

    def close(self):
        self.send({"quit": True})
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()


class App:
    def __init__(self, root, host):
        self.root = root
        self.link = Link(host)
        self.controls = {}
        self.original = {}
        self.sliders = {}
        self.pending = {}
        self.sent = {}
        self.loading = False
        self.yellow = dict(YELLOW_DEFAULT)
        self.photo = None
        self.frame_times = []
        self.last_count = 0
        self.closed = False
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(30, self.tick)
        root.after(100, self.flush)
        root.after(1000, self.update_rate)

    def _build(self):
        self.root.title("라즈봇 카메라 조절")
        font = ("Malgun Gothic", 10)
        self.root.option_add("*Font", font)
        left = ttk.Frame(self.root, padding=6)
        left.grid(row=0, column=0, sticky="n")
        right = ttk.Frame(self.root, padding=6)
        right.grid(row=0, column=1, sticky="n")

        self.stats = tk.StringVar(value="로봇에 연결하는 중...")
        ttk.Label(left, textvariable=self.stats, font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
        self.image = ttk.Label(left)
        self.image.pack()
        blank = Image.new("RGB", (640, 480), (30, 30, 30))
        self.photo = ImageTk.PhotoImage(blank)
        self.image.configure(image=self.photo)

        yellow_box = ttk.LabelFrame(left, text="노란 선 기준·찾는 범위 (화면 미리보기만, 주행 코드는 안 바뀜. 처음 값이 07번 기준)", padding=4)
        yellow_box.pack(fill="x", pady=(6, 0))
        self.show_mask = tk.BooleanVar(value=True)
        ttk.Checkbutton(yellow_box, text="인식된 곳을 빨갛게", variable=self.show_mask).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(yellow_box, text="07번 기준으로", command=self.reset_yellow).grid(row=0, column=2, columnspan=2, sticky="e")
        self.yellow_vars = {}
        for index, (key, label, top) in enumerate((("h_min", "색상 최소", 179), ("h_max", "색상 최대", 179),
                                                   ("s_min", "진하기 최소", 255), ("v_min", "밝기 최소", 255))):
            row, col = 1 + index // 2, (index % 2) * 2
            ttk.Label(yellow_box, text=label).grid(row=row, column=col, sticky="e")
            var = tk.IntVar(value=self.yellow[key])
            tk.Scale(yellow_box, from_=0, to=top, orient="horizontal", length=220, variable=var,
                     command=lambda value, key=key: self.yellow.__setitem__(key, int(float(value)))).grid(row=row, column=col + 1)
            self.yellow_vars[key] = var
        self.roi_top = tk.IntVar(value=ROI_TOP)
        self.roi_bottom = tk.IntVar(value=ROI_BOTTOM)
        for col, (label, var) in enumerate((("찾는 범위 위 줄", self.roi_top), ("찾는 범위 아래 줄", self.roi_bottom))):
            ttk.Label(yellow_box, text=label).grid(row=3, column=col * 2, sticky="e")
            tk.Scale(yellow_box, from_=0, to=480, orient="horizontal", length=220,
                     variable=var).grid(row=3, column=col * 2 + 1)

        camera_box = ttk.LabelFrame(right, text="카메라 값 (움직이면 바로 적용)", padding=4)
        camera_box.pack(fill="x")
        self.auto_exposure = tk.BooleanVar(value=True)
        self.auto_white = tk.BooleanVar(value=True)
        ttk.Checkbutton(camera_box, text="노출 자동", variable=self.auto_exposure,
                        command=self.toggle_exposure).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(camera_box, text="화이트밸런스 자동", variable=self.auto_white,
                        command=self.toggle_white).grid(row=1, column=0, columnspan=2, sticky="w")
        for index, (name, label) in enumerate(CAMERA_SLIDERS):
            ttk.Label(camera_box, text=label).grid(row=index + 2, column=0, sticky="e", padx=(0, 4))
            slider = tk.Scale(camera_box, from_=0, to=100, orient="horizontal", length=300,
                              command=lambda value, name=name: self.slider_moved(name, value))
            slider.grid(row=index + 2, column=1)
            self.sliders[name] = slider

        buttons = ttk.Frame(right, padding=(0, 6))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="처음 값으로", command=self.restore).pack(side="left")
        ttk.Button(buttons, text="명령 복사", command=self.copy_command).pack(side="left", padx=6)
        self.note = tk.StringVar(value="창을 닫아도 값은 유지됩니다. 주행할 때는 이 창을 닫으세요(카메라는 한 프로그램만 씀).")
        ttk.Label(right, textvariable=self.note, wraplength=380, foreground="#444").pack(anchor="w")

    def load_controls(self, controls):
        self.loading = True
        self.controls = controls
        if not self.original:
            self.original = {name: info["value"] for name, info in controls.items() if "value" in info}
        for name, slider in self.sliders.items():
            info = controls.get(name)
            if not info:
                slider.configure(state="disabled")
                continue
            slider.configure(state="normal", from_=info["min"], to=info["max"])
            slider.set(info["value"])
            self.sent[name] = info["value"]
        if "auto_exposure" in controls:
            self.auto_exposure.set(controls["auto_exposure"]["value"] != AUTO_EXPOSURE_MANUAL)
        if "white_balance_automatic" in controls:
            self.auto_white.set(controls["white_balance_automatic"]["value"] != 0)
        self.update_states()
        self.root.update_idletasks()
        self.root.after(50, lambda: setattr(self, "loading", False))

    def update_states(self):
        self.sliders["exposure_time_absolute"].configure(state="disabled" if self.auto_exposure.get() else "normal")
        self.sliders["white_balance_temperature"].configure(state="disabled" if self.auto_white.get() else "normal")

    def slider_moved(self, name, value):
        value = int(float(value))
        if self.loading or self.sent.get(name) == value:
            return
        self.pending[name] = value

    def flush(self):
        if self.pending:
            self.link.send({"set": list(self.pending.items())})
            self.sent.update(self.pending)
            self.pending = {}
        if not self.closed:
            self.root.after(100, self.flush)

    def toggle_exposure(self):
        if self.auto_exposure.get():
            self.link.send({"set": [("auto_exposure", AUTO_EXPOSURE_ON)]})
        else:
            value = int(self.sliders["exposure_time_absolute"].get())
            self.link.send({"set": [("auto_exposure", AUTO_EXPOSURE_MANUAL), ("exposure_time_absolute", value)]})
        self.update_states()

    def toggle_white(self):
        if self.auto_white.get():
            self.link.send({"set": [("white_balance_automatic", 1)]})
        else:
            value = int(self.sliders["white_balance_temperature"].get())
            self.link.send({"set": [("white_balance_automatic", 0), ("white_balance_temperature", value)]})
        self.update_states()

    def restore(self):
        if not self.original:
            return
        self.link.send({"set": setting_order(self.original), "read": True})
        self.note.set("처음 값으로 되돌렸습니다.")

    def reset_yellow(self):
        for key, value in YELLOW_DEFAULT.items():
            self.yellow_vars[key].set(value)
            self.yellow[key] = value
        self.roi_top.set(ROI_TOP)
        self.roi_bottom.set(ROI_BOTTOM)

    def current_values(self):
        values = {name: int(slider.get()) for name, slider in self.sliders.items() if name in self.controls}
        values["auto_exposure"] = AUTO_EXPOSURE_ON if self.auto_exposure.get() else AUTO_EXPOSURE_MANUAL
        values["white_balance_automatic"] = 1 if self.auto_white.get() else 0
        return values

    def copy_command(self):
        order = setting_order(self.current_values())
        command = " && ".join("v4l2-ctl -d /dev/video0 -c %s=%d" % item for item in order)
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.note.set("복사했습니다. 전원을 껐다 켠 뒤 로봇 터미널에 붙여 넣으면 지금 값이 됩니다.")

    def tick(self):
        if self.closed:
            return
        while not self.link.messages.empty():
            message = self.link.messages.get()
            if "controls" in message:
                self.load_controls(message["controls"])
            elif "error" in message:
                self.note.set("값을 못 넣었습니다: " + message["error"])
            elif "fatal" in message:
                self.stats.set(message["fatal"])
            elif "closed" in message:
                self.stats.set("연결이 끊겼습니다. " + message["closed"])
        jpeg = self.link.take_frame()
        if jpeg is not None:
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None and frame.shape[:2] == (480, 640):
                top = max(0, min(470, self.roi_top.get()))
                bottom = max(top + 10, min(480, self.roi_bottom.get()))
                result = measure(frame, self.yellow, top, bottom)
                shown = annotate(frame, result, self.show_mask.get(), top, bottom)
                self.photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)))
                self.image.configure(image=self.photo)
                self.last_result = result
                self.stats.set("노란 점 %d개 · 선 덩어리 %d개 · 화면 밝기 %.0f · 하얗게 날아감 %.0f%% · %.0f장/초"
                               % (result["yellow"], len(result["blobs"]), result["brightness"],
                                  result["washed"], getattr(self, "rate", 0)))
        self.root.after(30, self.tick)

    def update_rate(self):
        if self.closed:
            return
        self.rate = self.link.frames_received - self.last_count
        self.last_count = self.link.frames_received
        self.root.after(1000, self.update_rate)

    def close(self):
        self.closed = True
        self.link.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="라즈봇 카메라 실시간 화면 + 값 조절")
    parser.add_argument("--host", default="raspbot-03.local")
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.host)
    root.mainloop()


if __name__ == "__main__":
    main()
