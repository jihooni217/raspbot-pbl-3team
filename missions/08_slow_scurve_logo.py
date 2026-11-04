#!/usr/bin/env python3
# 지시서: (아직 없음) — 07(specs/07-camera-lane.md) 노란 차선 주행을 기준으로 만든 08번 임무.
#   1) 바닥의 직진·우회전 화살표를 센다. 1번째(출발 직후)는 무시하고 07처럼 직진한다.
#   2) 2번째 화살표를 본 뒤 「천천히」 글자도 보이면 오른쪽 노란 선만 따라가 S자 길로 들어가고 절반 속도로 바꾼다.
#      「천천히」가 안 보이면 꺾지 않고 직진한다(안전장치).
#   3) 「천천히」 글자를 지나면 다시 두 선 가운데를 따라가되, S자 길에서도 절반 속도를 유지한다.
#   4) 로터리에서 대구대 로고를 보면 일단 정지하고, 속도 비율을 「천천히」 이전(원래 속도)으로 되돌린 채
#      다음 작업을 위해 멈춰 기다린다(아무 키나 누르면 종료).
# 화살표·「천천히」·로고는 YOLO(80가지 물체)에 없으므로 OpenCV 그림 맞추기(ORB 특징점)로 찾는다.
# 기준 사진(assets/08_test_phone_refs/)은 사용자가 트랙에서 찍은 휴대폰 사진에서 표지 부분만 잘라 낸 **테스트용 임시본**이다.
#   라즈봇 카메라(640x480, 짐벌 80°/25°)로 찍은 사진으로 바꾸면 더 잘 맞는다.
# --check는 드라이버를 불러오거나 모터 명령을 보내지 않는다.
"""화살표 세기 → 2번째+천천히에서 오른쪽 진입 → 절반 속도 S자 → 대구대 로고에서 정지 대기."""
import argparse
import csv
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import threading
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'missions' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lane = load('mission08_lane', '07_camera_lane.py')   # 07 차선 계산·녹화 부품을 그대로 쓴다
line = lane.line                                     # 02 바퀴/정지/키 입력 부품
STOP = lane.STOP

# ── 바꿔 볼 값 (시험해 보고 조가 정한다) ──────────────────────────────
SLOW_SCALE = 0.5            # 감속 구간에서 07 바퀴 값에 곱하는 비율 (절반 속도: 기본35→약18, 최대80→40)
TURN_ARROW_NUMBER = 2       # 몇 번째 화살표에서 오른쪽으로 들어갈지
TURN_CHECK_SECONDS = 2.0    # 그 화살표를 본 뒤 이 시간 안에 「천천히」가 보여야 꺾는다
ARROW_REARM_FRAMES = 10     # 화살표가 새 화면 연속 이만큼 안 보여야 다음 화살표를 셀 준비가 된다
PASS_FRAMES = 5             # 「천천히」를 본 뒤 새 화면 연속 이만큼 안 보이면 「지나갔다」고 본다
REF_DIR = ROOT / 'assets' / '08_test_phone_refs'   # ⚠️ 테스트용 휴대폰 사진. 라즈봇 카메라 사진으로 교체 예정
ARROW_REFS = [REF_DIR / 'arrow_straight_right.jpg',    # 교차로 쪽에서 비스듬히
              REF_DIR / 'arrow_straight_right_2.jpg',  # 정면·먼 거리
              REF_DIR / 'arrow_straight_right_3.jpg',  # 정면·아주 가까이
              REF_DIR / 'arrow_straight_right_4.jpg',  # 시작 부분 화살표·먼 거리(아래 이음 조각 포함)
              REF_DIR / 'arrow_straight_right_5.jpg']  # 시작 부분 화살표·가까이
SLOW_REFS = [REF_DIR / 'slow_text.jpg',     # 로봇이 「천천히」를 정면으로 볼 때
             REF_DIR / 'slow_text_2.jpg',   # 비스듬하지만 글자가 가장 잘 보일 때
             REF_DIR / 'slow_text_3.jpg',   # 횡단보도 앞에서 정면·먼 거리
             REF_DIR / 'slow_text_4.jpg']   # 횡단보도 앞에서 정면·가까이
LOGO_REFS = [REF_DIR / 'daegu_logo.jpg']    # 로봇 높이에서 본 로고
REF_MAX_SIDE = 640          # 기준 사진 긴 변을 이 크기 이하로 줄여서 특징점을 뽑는다 (카메라 화면 폭과 같게)
RATIO = 0.75                # 특징점 짝 고르기(Lowe 비율)
MIN_GOOD = 15               # 좋은 짝이 이 개수 이상이어야 모양 검사로 넘어간다
MIN_INLIERS = 12            # 모양(호모그래피)까지 맞는 짝이 이 개수 이상이면 「보임」
CONFIRM_FRAMES = 3          # 새 화면 연속 몇 장에서 보여야 인정할지 (잘못 보기 방지)

# 임무 상태
NORMAL = 'NORMAL'           # 07처럼 두 선 가운데, 원래 속도. 화살표를 센다
TURNCHECK = 'TURNCHECK'     # 꺾을 화살표를 봄. 직진하며 「천천히」가 보이는지 확인
KEEPRIGHT = 'KEEPRIGHT'     # 오른쪽 노란 선만 따라가 S자 길로 진입, 절반 속도
SLOW = 'SLOW'               # 「천천히」를 지남. 두 선 가운데 S자 주행, 절반 속도
LOGOSTOP = 'LOGOSTOP'       # 로고에서 정지 대기. 속도 비율은 원래대로 되돌림
SLOW_MODES = (KEEPRIGHT, SLOW)


class TemplateMatcher:
    """기준 사진 한 장과 카메라 화면을 ORB 특징점으로 비교한다."""

    def __init__(self, path, name):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise FileNotFoundError(f'{name} 기준 사진을 읽지 못했습니다: {path}')
        scale = REF_MAX_SIDE / max(image.shape)
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        self.name = name
        self.size = image.shape[::-1]  # (w, h)
        self.orb = cv2.ORB_create(nfeatures=1000)
        self.keypoints, self.descriptors = self.orb.detectAndCompute(image, None)
        if self.descriptors is None or len(self.keypoints) < MIN_GOOD:
            raise ValueError(f'{name} 기준 사진에 특징점이 너무 적습니다({len(self.keypoints)}개). '
                             '더 선명하고 무늬가 보이게 찍은 사진을 쓰세요.')
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def match(self, keypoints, descriptors):
        """(좋은 짝 수, 모양까지 맞는 짝 수, 화면 속 네 모서리 또는 None)."""
        if descriptors is None or len(keypoints) < 2:
            return 0, 0, None
        good = []
        for pair in self.matcher.knnMatch(self.descriptors, descriptors, k=2):
            if len(pair) == 2 and pair[0].distance < RATIO * pair[1].distance:
                good.append(pair[0])
        if len(good) < MIN_GOOD:
            return len(good), 0, None
        src = np.float32([self.keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if homography is None:
            return len(good), 0, None
        inliers = int(mask.sum())
        w, h = self.size
        corners = cv2.perspectiveTransform(
            np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2), homography)
        return len(good), inliers, corners.reshape(-1, 2)


class MatcherGroup:
    """같은 표지를 여러 각도에서 찍은 기준 사진들. 가장 잘 맞는 사진의 결과를 쓴다."""

    def __init__(self, paths, name):
        self.matchers = [TemplateMatcher(path, name) for path in paths]

    def match(self, keypoints, descriptors):
        return max((m.match(keypoints, descriptors) for m in self.matchers), key=lambda r: (r[1], r[0]))


class SignWatcher:
    """카메라 최신 화면에서 기준 사진들을 따로(스레드) 찾는다. 주행 반복은 결과만 읽는다."""

    def __init__(self, camera, matchers):
        self.camera = camera
        self.matchers = matchers
        self.orb = cv2.ORB_create(nfeatures=1500)
        self.lock = threading.Lock()
        self.result = dict(sequence=None, found={}, scores={}, corners={})
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, name='sign-watcher')

    def run(self):
        last = None
        try:
            while not self.stop_event.is_set():
                frame, sequence = self.camera.snapshot()
                if sequence == last:
                    self.stop_event.wait(0.01)
                    continue
                last = sequence
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                keypoints, descriptors = self.orb.detectAndCompute(gray, None)
                found, scores, corners = {}, {}, {}
                for name, matcher in self.matchers.items():
                    good, inliers, box = matcher.match(keypoints, descriptors)
                    found[name] = inliers >= MIN_INLIERS
                    scores[name] = (good, inliers)
                    corners[name] = box if found[name] else None
                with self.lock:
                    self.result = dict(sequence=sequence, found=found, scores=scores, corners=corners)
        except Exception as exc:
            self.error = exc

    def start(self):
        self.thread.start()
        return self

    def latest(self):
        if self.error is not None:
            raise RuntimeError('그림 맞추기 스레드 오류') from self.error
        with self.lock:
            return dict(self.result)

    def close(self):
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join()


class MissionState:
    """화살표 세기·꺾기 확인·감속·로고 정지를 장치 없이 계산한다. 새 화면마다 한 번만 센다."""

    def __init__(self):
        self.mode = NORMAL
        self.streak = dict(arrow=0, slow=0, logo=0)
        self.missing = dict(arrow=0, slow=0)
        self.arrow_count = 0
        self.arrow_armed = True        # 출발할 때 이미 보이는 화살표도 1번째로 센다
        self.turn_check_since = None
        self.slow_seen = False
        self.scale = 1.0
        self.last_sequence = None
        self.note = ''

    def update(self, seen, now):
        if seen['sequence'] is None or seen['sequence'] == self.last_sequence:
            return self.mode   # 같은 화면을 두 번 세지 않는다
        self.last_sequence = seen['sequence']
        for name in ('arrow', 'slow', 'logo'):
            visible = bool(seen['found'].get(name))
            self.streak[name] = self.streak[name] + 1 if visible else 0
            if name in self.missing:
                self.missing[name] = 0 if visible else self.missing[name] + 1
        confirmed = {name: self.streak[name] >= CONFIRM_FRAMES for name in self.streak}

        # 화살표 세기: 연속으로 보이면 1개, 충분히 안 보인 뒤에야 다음 화살표를 센다
        if self.arrow_armed and confirmed['arrow']:
            self.arrow_count += 1
            self.arrow_armed = False
            self.note = f'arrow {self.arrow_count}'
            if self.mode == NORMAL and self.arrow_count == TURN_ARROW_NUMBER:
                self.mode = TURNCHECK
                self.turn_check_since = now
        elif not self.arrow_armed and self.missing['arrow'] >= ARROW_REARM_FRAMES:
            self.arrow_armed = True

        if self.mode == TURNCHECK:
            if confirmed['slow']:
                self.mode, self.scale, self.slow_seen = KEEPRIGHT, SLOW_SCALE, True
                self.note = 'turn right'
            elif now - self.turn_check_since >= TURN_CHECK_SECONDS:
                self.mode = NORMAL          # 「천천히」가 안 보이면 꺾지 않고 직진
                self.note = 'no slow text: go straight'
        elif self.mode == KEEPRIGHT:
            if self.slow_seen and self.missing['slow'] >= PASS_FRAMES:
                self.mode = SLOW            # 「천천히」를 지남: 두 선 가운데, 절반 속도 유지
                self.note = 'passed slow text'
        if self.mode in SLOW_MODES and confirmed['logo']:
            self.mode, self.scale = LOGOSTOP, 1.0   # 정지하고 속도 비율은 원래대로
            self.note = 'logo stop'
        return self.mode

    def output(self, lane_speeds):
        """07이 계산한 바퀴 값을 모드에 맞게 바꾼다."""
        if self.mode == LOGOSTOP:
            return STOP
        return tuple(int(round(v * self.scale)) for v in lane_speeds)


def right_line_only(frame):
    """오른쪽 노란 선만 쓴다: 가장 오른쪽 덩어리의 가장 아래 행 평균 x. 07의 한쪽 선 계산으로 넘긴다."""
    parts = lane.find_components(frame)
    result = dict(left=None, right=None, left_count=0, right_count=0)
    if not parts:
        return result
    part = max(parts, key=lambda c: c[0])
    xs, ys = part.xs, part.ys
    result['right'] = float(xs[ys == ys.max()].mean())
    result['right_count'] = part[1]
    return result


def annotated(frame, report, mission, seen, wheels):
    out = lane.annotated(frame, report)
    for name, color in (('arrow', (255, 255, 255)), ('slow', (255, 128, 0)), ('logo', (0, 0, 255))):
        box = seen['corners'].get(name)
        if box is not None:
            cv2.polylines(out, [np.int32(box)], True, color, 2)
    scores = seen['scores']
    cv2.putText(out, f"MODE {mission.mode} ARROWS {mission.arrow_count} SCALE {mission.scale} OUT {wheels}",
                (8, 380), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"ARROW {scores.get('arrow', (0, 0))} SLOW {scores.get('slow', (0, 0))} "
                     f"LOGO {scores.get('logo', (0, 0))}",
                (8, 405), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1, cv2.LINE_AA)
    return out


class Display(lane.LatestDisplay):
    def update(self, frame, report, mission=None, seen=None, wheels=STOP):
        mission = mission or MissionState()
        seen = seen or dict(scores={}, corners={})
        marked = annotated(frame, report, mission, seen, wheels)
        with self.lock:
            self.frame = marked
            self.sequence += 1


FIELDS = lane.FIELDS + ('임무모드', '화살표수', '속도비율', '출력바퀴값', '화살표_짝', '천천히_짝', '로고_짝', '메모')


def run_loop(camera, watcher, recorder, display, key_pressed, stream, check=False, bot=None):
    if not check and bot is None:
        raise ValueError('주행 모드에는 바퀴 장치가 필요합니다.')
    controller = lane.LaneController()
    mission = MissionState()
    started = time.monotonic()
    next_print = started
    sequence = frame = None
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader()
    last_record = None
    last_note = ''
    reason = '키 입력'
    try:
        while True:
            if key_pressed():
                break
            seen = watcher.latest()
            mission.update(seen, time.monotonic())
            if mission.note != last_note:
                print(f'08 상황: {mission.note} (모드 {mission.mode}, 화살표 {mission.arrow_count}개)', flush=True)
                if mission.mode == LOGOSTOP:
                    print('대구대 로고 확인: 정지 대기 중. 속도 비율은 원래대로 되돌렸습니다. 아무 키나 누르면 종료합니다.',
                          flush=True)
                last_note = mission.note
            if mission.mode == LOGOSTOP:
                if not check:
                    line.drive(bot, STOP)
                candidate, new_sequence = camera.snapshot()
                if new_sequence != sequence:
                    frame, sequence = candidate, new_sequence
                report = controller.report()
            else:
                controller.tick(time.monotonic())
                candidate, new_sequence = camera.snapshot()
                received_at = time.monotonic()
                if new_sequence != sequence:
                    if mission.mode == KEEPRIGHT:
                        lines = right_line_only(candidate)
                    else:
                        lines = lane.find_lines(candidate, controller.previous, controller.width,
                                                controller.single_name)
                    controller.update(lines, received_at)
                    frame, sequence = candidate, new_sequence
                if key_pressed():
                    break
                controller.tick(time.monotonic())
                report = controller.report()
                if not check:
                    line.drive(bot, mission.output(report['speeds']))
            wheels = mission.output(report['speeds'])
            display.update(frame, report, mission, seen, wheels)
            if recorder is not None:
                recorder.set_status(f"{mission.mode} A{mission.arrow_count} {report['state']}")
                recorder.check()
            now = time.monotonic()
            current = (sequence, report['state'], mission.mode, mission.arrow_count)
            if current != last_record:
                row = lane.row_values(report, now - started, sequence, check)
                row.update({'임무모드': mission.mode, '화살표수': mission.arrow_count, '속도비율': mission.scale,
                            '출력바퀴값': json.dumps(wheels),
                            '화살표_짝': json.dumps(seen['scores'].get('arrow')),
                            '천천히_짝': json.dumps(seen['scores'].get('slow')),
                            '로고_짝': json.dumps(seen['scores'].get('logo')), '메모': mission.note})
                writer.writerow(row)
                stream.flush()
                last_record = current
            if now >= next_print:
                print('08 계산: ' + json.dumps(dict(mode=mission.mode, arrows=mission.arrow_count,
                                                    scale=mission.scale, wheels=wheels,
                                                    state=report['state'], scores=seen['scores']),
                                                ensure_ascii=False), flush=True)
                next_print = now + 1
            if mission.mode != LOGOSTOP and controller.stopped:
                reason = report['state']
                break
            time.sleep(.01)
    except KeyboardInterrupt:
        reason = 'Ctrl+C'
    finally:
        if not check:
            line.stop_all(bot)
    return reason, mission.mode


def _main(stop_requested):
    parser = argparse.ArgumentParser(description='08: 화살표 세기 → 2번째+천천히에서 오른쪽 진입 → 절반 속도 S자 '
                                                 '→ 대구대 로고 정지 대기 / --check는 모터 명령 없는 카메라 점검')
    parser.add_argument('--check', action='store_true', help='모터 없이 모드·그림 맞추기 점수·바퀴 계산 값을 1초마다 출력')
    parser.add_argument('--arrow-ref', type=Path, nargs='+', default=ARROW_REFS, help='직진·우회전 화살표 기준 사진(여러 장 가능)')
    parser.add_argument('--slow-ref', type=Path, nargs='+', default=SLOW_REFS, help='「천천히」 글자 기준 사진(여러 장 가능)')
    parser.add_argument('--logo-ref', type=Path, nargs='+', default=LOGO_REFS, help='대구대 로고 기준 사진(여러 장 가능)')
    args = parser.parse_args()
    # 기준 사진부터 확인한다 — 없으면 바퀴를 움직이기 전에 끝낸다.
    matchers = dict(arrow=MatcherGroup(args.arrow_ref, '직진·우회전 화살표'),
                    slow=MatcherGroup(args.slow_ref, '천천히 글자'),
                    logo=MatcherGroup(args.logo_ref, '대구대 로고'))
    camera = recorder = watcher = bot = None
    entered = False
    stamp = datetime.now(lane.KST).strftime('%Y%m%d_%H%M%S_%f')
    path = ROOT / 'results' / f'mission08_{stamp}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    display = Display()
    try:
        with line.keyboard_stop() as terminal_key:
            key_pressed = lambda: stop_requested.is_set() or terminal_key()
            if not args.check:
                from Raspbot_Lib import Raspbot
                bot = Raspbot()
                line.stop_all(bot)
            camera = lane.video.LatestCamera()
            camera.start()
            if stop_requested.is_set():
                return
            watcher = SignWatcher(camera, matchers).start()
            first, _ = camera.snapshot()
            display.update(first, lane.LaneController().report())
            recorder = lane.LaneVideo(display)
            recorder.start()
            with path.open('x', newline='', encoding='utf-8') as stream:
                entered = True
                reason, mode = run_loop(camera, watcher, recorder, display, key_pressed, stream,
                                        args.check, bot)
            print(f'종료: {reason}, 마지막 모드: {mode}, 기록: {path}', flush=True)
    finally:
        errors = []
        if bot is not None and not entered:
            try:
                line.stop_all(bot)
            except Exception as exc:
                errors.append(exc)
        for resource in (recorder, watcher, camera):
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise RuntimeError('08 종료 정리 오류: ' + '; '.join(map(str, errors)))


def main():
    with lane.stop_signals() as requested:
        try:
            _main(requested)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
