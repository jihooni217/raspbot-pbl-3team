#!/usr/bin/env python3
# 지시서: specs/10_rotary_turn.md
"""
로고 앞 정지 상태에서 시작 -> 로터리 우측 깊숙이 진입 -> 안쪽 노란선 완만 추종 반바퀴 선회 -> 출구 차선 감지 시 직진 탈출
--check 플래그는 드라이버를 불러오거나 모터 명령을 보내지 않는다.
"""
import argparse
import csv
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from zoneinfo import ZoneInfo

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'missions' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


line = load('rotary_stop', '02_line.py')
video = load('rotary_blackbox', '03_video.py')
STOP = (0, 0, 0, 0)
KST = ZoneInfo('Asia/Seoul')

# ----------------- 주요 하이퍼파라미터 튜닝 -----------------
ROI_TOP, ROI_BOTTOM = 180, 380  # 차선 추종 관심영역 (180~379행)
BASE_SPEED = 30                  # 로터리 내 선회 속도 (속도를 소폭 올려 원심력 확보)
STEERING_K = 0.25                # 조향 P 게인 (0.35 -> 0.25 완화로 급격한 안쪽 쏠림 방지)
TARGET_X = 270                   # 안쪽 노란선 추종 목표 x좌표 (220 -> 270으로 변경하여 회전 반경 확대)

START_DELAY_SECONDS = 1.0        # 시작 직후 안정화 대기 시간 (초)
ENTRY_SECONDS = 1.8              # 우측 진입로 진입 기동 시간 (1.2 -> 1.8초로 연장하여 바깥 궤적 진입)
ENTRY_SPEEDS = (38, 38, 15, 15)  # 우측 진입 시 바퀴 속도 (좌측 구동력을 대폭 강화하여 우측으로 깊게 진입)

MIN_ROTARY_SECONDS = 5.0         # 진입 잔여선 및 내부 선 오인식 방지용 최소 선회 시간 (3.5 -> 5.0초 증가)
EXIT_SPEED = 32                  # 탈출 구간 기본 직진 속도
EXIT_DRIVE_SECONDS = 1.5         # 출구 정렬 확인 후 탈출 주행 시간 (초)
SEARCH_SECONDS = 1.0             # 선 유실 한계 시간 (초)
# -----------------------------------------------------------


def find_lines(frame):
    """07번 규격 동일 노란선 검출 (180~380행 띠 사용)"""
    if frame is None or frame.shape != (480, 640, 3) or frame.dtype != np.uint8:
        raise ValueError('차선 입력 화면은 640x480 uint8 BGR이어야 합니다.')
    hsv = cv2.cvtColor(frame[ROI_TOP:ROI_BOTTOM], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (15, 80, 100), (40, 255, 255))
    result = {}
    for name, start, end in (('left', 0, 320), ('right', 320, 640)):
        _, xs = np.nonzero(mask[:, start:end])
        result[name + '_count'] = len(xs)
        result[name] = float(xs.mean() + start) if len(xs) >= 50 else None
    return result


def wheel_speeds_rotary(center_x):
    """안쪽 노란선(left)을 TARGET_X에 유지하기 위한 비례 조향 바퀴값 계산"""
    correction = STEERING_K * (center_x - TARGET_X)
    left = max(0, min(50, round(BASE_SPEED + correction)))
    right = max(0, min(50, round(BASE_SPEED - correction)))
    return (left, left, right, right)


def wheel_speeds_center(center_x):
    """탈출 시 양쪽 차선 중심(320px) 추종 바퀴값 계산"""
    correction = 0.4 * (center_x - 320)
    left = max(0, min(50, round(EXIT_SPEED + correction)))
    right = max(0, min(50, round(EXIT_SPEED - correction)))
    return (left, left, right, right)


class PostStopRotaryController:
    """
    정지선 정차 상태에서 기동하는 로터리 제어기:
    1. READY        : 실행 직후 1초간 정지 상태로 카메라 및 환경 안정화
    2. ENTERING     : 우측 바깥 궤적으로 깊숙이 우회전 진입 (1.8초)
    3. CIRCLING     : 안쪽(좌측) 노란선 완만 추종 반바퀴 선회 (최소 5.0초 보장)
    4. EXIT_DRIVE   : 출구 양쪽 차선(left, right) 정렬 감지 시 중앙 추종 탈출 (1.5초)
    5. COMPLETED    : 미션 완료 정지
    """
    def __init__(self):
        self.state = 'READY'
        self.speeds = STOP
        self.stopped = False
        self.last_frame = None
        self.lost_since = None
        self.state_time = time.monotonic()
        self.exit_count = 0
        self.lines = dict(left=None, right=None, left_count=0, right_count=0)

    def tick(self, now):
        if self.stopped:
            return STOP
        if self.last_frame is not None and now - self.last_frame > 0.5:
            self.state = 'FRAMESTOP'
            self.stopped = True
            self.speeds = STOP
        elif self.lost_since is not None and now - self.lost_since >= SEARCH_SECONDS:
            self.state = 'LOSTSTOP'
            self.stopped = True
            self.speeds = STOP
        return self.speeds

    def update(self, lines, now):
        self.tick(now)
        if self.stopped:
            return STOP

        self.last_frame = now
        self.lines = dict(lines)
        elapsed = now - self.state_time
        left, right = lines['left'], lines['right']

        # 1. 출발 준비 대기
        if self.state == 'READY':
            self.speeds = STOP
            if elapsed >= START_DELAY_SECONDS:
                self.state = 'ENTERING'
                self.state_time = now
                print("[EVENT] 정지 상태에서 로터리 우측 바깥 궤적으로 진입 시작")

        # 2. 로터리 우측 깊숙이 진입 기동
        elif self.state == 'ENTERING':
            self.speeds = ENTRY_SPEEDS
            if elapsed >= ENTRY_SECONDS:
                self.state = 'CIRCLING'
                self.state_time = now
                self.exit_count = 0
                print("[EVENT] 바깥 궤적 진입 완료 -> 안쪽 선 완만 추종 선회 시작")

        # 3. 안쪽 선 추종 선회 및 엄격한 출구 탐색
        elif self.state == 'CIRCLING':
            # 안쪽 선(좌측 노란선) 추종
            if left is not None:
                track_point = left
                self.lost_since = None
            elif right is not None:
                track_point = right - 240
                self.lost_since = None
            else:
                track_point = TARGET_X
                if self.lost_since is None:
                    self.lost_since = now

            self.speeds = wheel_speeds_rotary(track_point)

            # 5초 이상 선회 후 엄격한 출구 정렬 검사 (원 내부 조기 정지 방지)
            if elapsed >= MIN_ROTARY_SECONDS:
                if left is not None and right is not None:
                    width = right - left
                    center_candidate = (left + right) / 2
                    # 실제 출구 직선로 폭(220~340px) 및 중심이 화면 중앙(280~360px)에 정렬되었을 때만 인정
                    if (220 <= width <= 340) and (280 <= center_candidate <= 360):
                        self.exit_count += 1
                        if self.exit_count >= 3:
                            self.state = 'EXIT_DRIVE'
                            self.state_time = now
                            self.lost_since = None
                            print("[EVENT] 출구 양쪽 차선 정렬 확인 -> 직진 탈출 주행")
                    else:
                        self.exit_count = 0
                else:
                    self.exit_count = 0

        # 4. 출구 직진 탈출 주행
        elif self.state == 'EXIT_DRIVE':
            if left is not None and right is not None:
                center = (left + right) / 2
                self.speeds = wheel_speeds_center(center)
                self.lost_since = None
            else:
                self.speeds = (EXIT_SPEED, EXIT_SPEED, EXIT_SPEED, EXIT_SPEED)
                if self.lost_since is None:
                    self.lost_since = now

            if elapsed >= EXIT_DRIVE_SECONDS:
                self.state = 'COMPLETED'
                self.stopped = True
                self.speeds = STOP
                print("[EVENT] 로터리 탈출 완료 -> 최종 정지")

        return self.speeds

    def report(self):
        return dict(self.lines, speeds=self.speeds, state=self.state, stopped=self.stopped)


def annotated(frame, report):
    out = frame.copy()
    cv2.rectangle(out, (0, ROI_TOP), (639, ROI_BOTTOM - 1), (255, 255, 255), 1)

    # 기준선 표시
    if report['state'] == 'EXIT_DRIVE':
        cv2.line(out, (320, ROI_TOP), (320, ROI_BOTTOM - 1), (0, 255, 0), 2)
    else:
        cv2.line(out, (TARGET_X, ROI_TOP), (TARGET_X, ROI_BOTTOM - 1), (255, 0, 0), 2)

    for name in ('left', 'right'):
        position = report[name]
        if position is not None:
            x = round(position)
            cv2.line(out, (x, ROI_TOP), (x, ROI_BOTTOM - 1), (0, 255, 255), 2)
            cv2.putText(out, f'{name.upper()} {position:.1f}', (max(2, min(480, x)), ROI_TOP - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 255), 1, cv2.LINE_AA)

    cv2.putText(out, f"STATE: {report['state']}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(out, f"WHEELS: {report['speeds']}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return out


class LatestDisplay:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0

    def update(self, frame, report):
        marked = annotated(frame, report)
        with self.lock:
            self.frame = marked
            self.sequence += 1

    def snapshot(self):
        with self.lock:
            if self.frame is None:
                raise RuntimeError('화면이 없습니다.')
            return self.frame.copy(), self.sequence


class RotaryVideo(video.BlackboxRecorder):
    def __init__(self, source):
        super().__init__(source)
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, name='rotary-video', daemon=True)

    def run(self):
        writer = None
        previous = None
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            start = time.monotonic()
            while not self.stop.is_set():
                if self.stop.wait(max(0, start + self.saved_frames / video.FPS - time.monotonic())):
                    break
                frame, sequence = self.camera.snapshot()
                if self.saved_frames % self.segment_frames == 0:
                    if writer is not None:
                        writer.release()
                        writer = None
                    writer = self._open_writer(frame)
                writer.write(self._overlay(frame))
                self.repeated_frames += int(sequence == previous)
                previous = sequence
                self.saved_frames += 1
        except Exception as exc:
            self.error = exc
        finally:
            if writer is not None:
                writer.release()

    def start(self):
        self.thread.start()
        return self

    def check(self):
        if self.error is not None:
            raise RuntimeError('녹화 오류') from self.error

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('녹화 종료 응답 없음')
        self.check()


FIELDS = ('경과초', '화면순번', '상태', '왼쪽선_x', '오른쪽선_x', '바퀴값', '모드')


def row_values(report, elapsed, sequence, check):
    return dict(zip(FIELDS, (round(elapsed, 4), sequence, report['state'], report['left'], report['right'],
                            json.dumps(report['speeds']), '읽기전용' if check else '주행')))


def run_loop(camera, recorder, display, key_pressed, stream, check=False, bot=None):
    if not check and bot is None:
        raise ValueError('주행 모드에는 바퀴 장치가 필요합니다.')
    controller = PostStopRotaryController()
    started = time.monotonic()
    next_print = started
    sequence = None
    frame = None
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader()
    last_record = None
    reason = '키 입력'
    try:
        while True:
            if key_pressed():
                break
            now = time.monotonic()
            controller.tick(now)
            candidate, new_sequence = camera.snapshot()
            received_at = time.monotonic()
            if new_sequence != sequence:
                lines = find_lines(candidate)
                now = time.monotonic()
                controller.update(lines, received_at)
                frame, sequence = candidate, new_sequence
            if key_pressed():
                break
            controller.tick(time.monotonic())
            report = controller.report()
            if not check:
                line.drive(bot, report['speeds'])
            display.update(frame, report)
            if recorder is not None:
                recorder.set_status(report['state'])
                recorder.check()
            current = (sequence, report['state'])
            if current != last_record:
                writer.writerow(row_values(report, now - started, sequence, check))
                stream.flush()
                last_record = current
            if now >= next_print:
                print('로터리 미션: ' + json.dumps(report, ensure_ascii=False), flush=True)
                next_print = now + 1
            if controller.stopped:
                reason = report['state']
                break
            time.sleep(.01)
    except KeyboardInterrupt:
        reason = 'Ctrl+C'
    finally:
        if not check:
            line.stop_all(bot)
    return reason, controller.report()


def main():
    parser = argparse.ArgumentParser(description='정지선 출발 -> 로터리 반바퀴 선회 및 탈출 미션')
    parser.add_argument('--check', action='store_true', help='모터 없이 카메라 감지만 점검')
    args = parser.parse_args()
    camera = recorder = bot = None
    entered = False
    stamp = datetime.now(KST).strftime('%Y%m%d_%H%M%S_%f')
    path = ROOT / 'results' / f'rotary_mission_{stamp}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    display = LatestDisplay()
    try:
        with line.keyboard_stop() as key_pressed:
            if not args.check:
                from Raspbot_Lib import Raspbot
                bot = Raspbot()
                line.stop_all(bot)
            camera = video.LatestCamera()
            camera.start()
            first, _ = camera.snapshot()
            display.update(first, PostStopRotaryController().report())
            recorder = RotaryVideo(display)
            recorder.start()
            with path.open('x', newline='', encoding='utf-8') as stream:
                entered = True
                reason, report = run_loop(camera, recorder, display, key_pressed, stream, args.check, bot)
            print(f'종료: {reason}, 기록: {path}', flush=True)
    finally:
        errors = []
        if bot is not None and not entered:
            try:
                line.stop_all(bot)
            except Exception as exc:
                errors.append(exc)
        for resource in (recorder, camera):
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise RuntimeError('정리 오류: ' + '; '.join(map(str, errors)))


if __name__ == '__main__':
    main()