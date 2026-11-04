#!/usr/bin/env python3
# 08번 임무(missions/08_slow_scurve_logo.py)의 기준 사진을 라즈봇 카메라로 찍는 도구.
# 바퀴는 움직이지 않는다. 카메라 짐벌만 주행 때와 같은 정면(좌우 80° · 위아래 25°)으로 맞춘다.
# 사진은 글자·상자 없이 640x480 원본 그대로 results/ref_photos/ 에 저장한다.
#
# 쓰는 법 (라즈봇 폴더에서):
#   python3 tools/capture_ref.py --name arrow     # 화살표 찍기
#   python3 tools/capture_ref.py --name slow      # 「천천히」 찍기
#   python3 tools/capture_ref.py --name logo      # 대구대 로고 찍기
#   - Enter          : 지금 화면을 한 장 저장
#   - 이름 + Enter   : 이름을 바꾼다 (예: logo 를 치면 다음부터 logo_ 로 저장)
#   - q + Enter      : 끝내기
#   --no-servo       : 짐벌을 움직이지 않고 지금 각도 그대로 찍기
"""라즈봇 카메라 기준 사진 찍기 (바퀴 안 움직임)."""
import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import cv2

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'results' / 'ref_photos'
PAN, TILT = 80, 25  # 주행 때 카메라 정면 (specs/01-camera-center.md)
KST = ZoneInfo('Asia/Seoul')


def load_video():
    spec = importlib.util.spec_from_file_location('capture_video', ROOT / 'missions' / '03_video.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def center_servo():
    from Raspbot_Lib import Raspbot
    bot = Raspbot()
    bot.Ctrl_Servo(1, PAN)
    time.sleep(0.5)
    bot.Ctrl_Servo(2, TILT)
    time.sleep(0.5)
    print(f'카메라 짐벌: 좌우 {PAN}° · 위아래 {TILT}° (주행 때와 같은 각도)', flush=True)


def save(camera, name, number):
    time.sleep(0.2)                      # 라즈봇을 내려놓은 뒤 흔들림이 멈추도록 잠깐 기다린다
    frame, sequence = camera.snapshot()  # 카메라 스레드가 가진 가장 최근 화면
    stamp = datetime.now(KST).strftime('%Y%m%d_%H%M%S')
    path = OUT_DIR / f'{stamp}_{name}_{number:02d}.jpg'
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise RuntimeError(f'사진을 저장하지 못했습니다: {path}')
    height, width = frame.shape[:2]
    print(f'저장: {path.relative_to(ROOT)} ({width}x{height}, 화면 순번 {sequence})', flush=True)


def main():
    parser = argparse.ArgumentParser(description='08 기준 사진 찍기 — 바퀴는 움직이지 않음')
    parser.add_argument('--name', default='ref', help='사진 이름 앞부분 (arrow · slow · logo 등)')
    parser.add_argument('--no-servo', action='store_true', help='짐벌 각도를 바꾸지 않음')
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_servo:
        center_servo()
    video = load_video()
    camera = video.LatestCamera()
    camera.start()
    name, number = args.name, 1
    print('Enter = 한 장 저장 · 이름 입력 후 Enter = 이름 바꾸기 · q + Enter = 끝', flush=True)
    try:
        while True:
            command = input(f'[{name}] > ').strip()
            if command.lower() in ('q', 'quit', 'exit'):
                break
            if command:
                name, number = command, 1
                print(f'이름을 {name} 으로 바꿨습니다.', flush=True)
                continue
            save(camera, name, number)
            number += 1
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        camera.close()
    print(f'끝. 사진 폴더: {OUT_DIR.relative_to(ROOT)}', flush=True)


if __name__ == '__main__':
    main()
