#!/usr/bin/env python3
# 지시서: specs/14-camera-auto-align.md
"""출발 전 카메라 측정/보정. import와 --photo는 장치에 접근하지 않는다."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
import math
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'results/camera_align'
REFERENCE = OUTPUT / 'reference.json'
LAST = OUTPUT / 'last.json'
DEFAULT_POSE = dict(pan=80, tilt=5)
LIMITS = dict(pan=(70, 90), tilt=(0, 15))
PIXELS_PER_DEGREE = 10.0
TOLERANCE = 10.0
DIRECTION_NOISE = 2.0
MAX_MOVES = 20
SETTLE_SECONDS = .3


def _fit_boundary(mask, side):
    height, width = mask.shape
    rows, positions = [], []
    for y in range(60, min(320, height)):
        xs = np.flatnonzero(mask[y])
        xs = xs[xs < width / 2] if side == 'left' else xs[xs >= width / 2]
        if len(xs) >= 3:
            rows.append(y)
            positions.append(float(np.median(xs)))
    if len(rows) < 40 or max(rows) - min(rows) < 60:
        return None
    ys, xs = np.asarray(rows), np.asarray(positions)
    fitted = np.polyfit(ys, xs, 1)
    for _ in range(5):
        residual = np.abs(xs - np.polyval(fitted, ys))
        good = residual <= max(3.0, 3 * float(np.median(residual)))
        if np.count_nonzero(good) < 30:
            return None
        fitted = np.polyfit(ys[good], xs[good], 1)
    slope, intercept = map(float, fitted)
    error = float(np.median(np.abs(xs[good] - np.polyval(fitted, ys[good]))))
    if error > 5 or (side == 'left' and slope >= -.2) or (side == 'right' and slope <= .2):
        return None
    # fitted line 가까이의 노란 픽셀이 다섯 행 이어지는 최초 위치.
    run = 0
    top = None
    for y in range(0, int(max(rows)) + 1):
        x = round(slope * y + intercept)
        if 0 <= x < width:
            support = np.count_nonzero(mask[y, max(0,x-15):min(width,x+16)]) >= 3
        else:
            support = False
        run = run + 1 if support else 0
        if run >= 5:
            top = y - 4
            break
    if top is None:
        return None
    return dict(slope=slope, intercept=intercept, top=int(top),
                fit_min_y=int(min(rows)), fit_max_y=int(max(rows)),
                median_error_px=error, inlier_rows=int(np.count_nonzero(good)))


def measure(frame):
    """640x480 BGR 한 장에서 두 노란 경계의 투영 기하를 잰다.

    lane_top은 바닥 끝의 대안 지표다. 아래 폭은 y=479까지 직선 연장한 값이며
    실제 화면 밖 x좌표도 보존한다. 양쪽 경계가 믿을 만하지 않으면 reliable=False.
    """
    if frame is None or frame.shape != (480, 640, 3) or frame.dtype != np.uint8:
        raise ValueError('측정 화면은 640x480 uint8 BGR이어야 합니다.')
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (15, 80, 100), (40, 255, 255))
    left, right = (_fit_boundary(mask, side) for side in ('left', 'right'))
    result = dict(reliable=False, reason='차선 안 보임 — START에 차선 가운데로 놓아 주세요',
                  vx=None, vy=None, lane_top=None, floor_top=None, width=None,
                  width_y=479, width_extrapolated=True, left=left, right=right)
    if left is None or right is None:
        return result
    vy = (right['intercept'] - left['intercept']) / (left['slope'] - right['slope'])
    vx = left['slope'] * vy + left['intercept']
    bottom_left = left['slope'] * 479 + left['intercept']
    bottom_right = right['slope'] * 479 + right['intercept']
    width = bottom_right - bottom_left
    if not (0 <= vx < 640 and -80 <= vy < 264 and 200 <= width <= 4000 and
            abs(left['top'] - right['top']) <= 25):
        result['reason'] = '두 노란 경계의 직선/소실점이 불안정합니다 — START 가운데를 확인해 주세요'
        return result
    result.update(reliable=True, reason='OK', vx=float(vx), vy=float(vy),
                  lane_top=(left['top'] + right['top']) / 2,
                  width=float(width), bottom_left=float(bottom_left), bottom_right=float(bottom_right),
                  width_extrapolated=max(left['fit_max_y'], right['fit_max_y']) < 479)
    return result


def correction(measured, reference):
    """화면 오차와 바라볼 방향. 서보 +/− 부호를 추정하지 않는다."""
    if not measured['reliable']:
        return dict(reliable=False, reason=measured['reason'])
    dx = measured['vx'] - reference['vx_ref']
    dy = measured['lane_top'] - reference['lane_top_ref']
    return dict(reliable=True, dx_px=dx, dy_px=dy,
                pan_view='RIGHT' if dx > DIRECTION_NOISE else 'LEFT' if dx < -DIRECTION_NOISE else 'NONE',
                tilt_view='DOWN' if dy > DIRECTION_NOISE else 'UP' if dy < -DIRECTION_NOISE else 'NONE',
                pan_view_degrees=dx / PIXELS_PER_DEGREE,
                tilt_view_degrees=dy / PIXELS_PER_DEGREE,
                aligned=abs(dx) <= TOLERANCE and abs(dy) <= TOLERANCE)


def annotated(frame, measured):
    out = frame.copy()
    for name in ('left','right'):
        line = measured.get(name)
        if line is not None:
            a, b = line['slope'], line['intercept']
            cv2.line(out, (round(b),0), (round(a * 479 + b),479), (0,0,255), 2)
    if measured['reliable']:
        cv2.circle(out, (round(measured['vx']),round(measured['vy'])), 5, (255,0,255), 2)
        cv2.line(out, (0,round(measured['lane_top'])), (639,round(measured['lane_top'])), (0,255,0), 1)
        text = f"VX {measured['vx']:.1f} LANE_TOP {measured['lane_top']:.1f} WIDTH479 {measured['width']:.1f} EXTRAP"
    else:
        text = 'UNRELIABLE: NEED BOTH LANES AT START'
    cv2.putText(out, text, (8,365), cv2.FONT_HERSHEY_SIMPLEX, .44, (0,255,255), 1)
    return out


def _validate_pose(pose):
    for name, (lo,hi) in LIMITS.items():
        value = pose.get(name)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f'{name}은 {lo}~{hi} 범위의 정수여야 합니다.')
    return {name:pose[name] for name in LIMITS}


def load_last(path=LAST):
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT_POSE, response_px_per_degree=dict(pan=None,tilt=None), source='default')
    data = json.loads(path.read_text(encoding='utf-8'))
    pose = _validate_pose(data)
    response = data.get('response_px_per_degree', {})
    values = {}
    for name in LIMITS:
        value = response.get(name)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value)
                                  or not 2 <= abs(value) <= 50):
            raise ValueError(f'{name} 서보 반응 기록이 올바르지 않습니다.')
        values[name] = float(value) if value is not None else None
    return dict(pose, response_px_per_degree=values, source=str(path))


def _command(bot, servo, angle):
    # 드라이버가 I2C 오류를 출력하고 계속 진행하는 경우도 실패로 취급한다.
    captured = io.StringIO()
    with redirect_stdout(captured):
        bot.Ctrl_Servo(servo,angle)
    output = captured.getvalue()
    if output:
        print(output,end='',flush=True)
    if 'i2c error' in output.casefold():
        raise RuntimeError('I2C error — 확장보드 전원과 5핀 선을 확인해 주세요')


def restore_saved_pose(bot, path=LAST, *, sleep_fn=time.sleep):
    """13번 시작 준비: 검증된 저장 각도 또는80/5 전송만 한다."""
    saved = load_last(path)
    pose = _validate_pose(saved)
    for name,servo in (('pan',1),('tilt',2)):
        _command(bot,servo,pose[name])
        sleep_fn(SETTLE_SECONDS)
    return dict(pose,source=saved['source'])


def _snapshot(camera):
    if hasattr(camera,'snapshot'):
        return camera.snapshot()
    ok,frame = camera.read()
    if not ok:
        raise RuntimeError('카메라 화면을 읽지 못했습니다.')
    return frame,None


def align(bot, camera, *, initial_pose=None, reference=None, last_path=LAST,
          sleep_fn=time.sleep):
    """한 번에 한 서보1°,0.3초 대기. 바퀴 API는 사용하지 않는다.

    camera는03의 LatestCamera(snapshot 권장) 또는 read() 카메라다.
    현재 명령 각도는 initial_pose 또는 last/80·5로 시작한다.
    실제 호출은 학교에서 START 준비 확인 후 한다. 시험은 가짜 장치를 전달한다.
    """
    saved = load_last(last_path)
    pose = _validate_pose(saved if initial_pose is None else initial_pose)
    response = dict(saved['response_px_per_degree'])
    if reference is None:
        reference = json.loads(REFERENCE.read_text(encoding='utf-8'))
    events = []
    moves = 0
    previous_token = None
    pending_probe = None
    status,reason = 'ERROR',''
    measured = None
    errors = None
    try:
        while True:
            frame,token = _snapshot(camera)
            if moves and token is not None and token == previous_token:
                status,reason = 'STALE_FRAME','새 화면이 도착하지 않아 멈췄습니다'
                break
            previous_token = token
            measured = measure(frame)
            errors = correction(measured,reference)
            events.append(dict(move=moves,**pose,measurement=measured,correction=errors))
            if not measured['reliable']:
                status,reason = 'NO_LANES',measured['reason']
                break
            if pending_probe is not None:
                axis,old_value,step = pending_probe
                feature = 'vx' if axis == 'pan' else 'lane_top'
                slope = (measured[feature] - old_value) / step
                if not 2 <= abs(slope) <= 50:
                    status,reason = 'UNRELIABLE_RESPONSE',f'{axis} 1° 반응을 믿기 어렵습니다. 학교에서 방향을 확인해 주세요'
                    break
                response[axis] = float(slope)
                pending_probe = None
            if errors['aligned']:
                status,reason = 'ALIGNED','기준 허용 오차 안으로 맞췄습니다'
                break
            if moves >= MAX_MOVES:
                status,reason = 'MAX_MOVES','20번 움직여도 맞지 않아 멈췄습니다'
                break
            axis = 'pan' if abs(errors['dx_px']) >= abs(errors['dy_px']) else 'tilt'
            error = errors['dx_px'] if axis == 'pan' else errors['dy_px']
            lo,hi = LIMITS[axis]
            if response[axis] is None:
                step = 1 if pose[axis] < hi else -1
                feature = 'vx' if axis == 'pan' else 'lane_top'
                pending_probe = axis,measured[feature],step
            else:
                step = 1 if -error / response[axis] > 0 else -1
            target = pose[axis] + step
            if not lo <= target <= hi:
                status,reason = 'LIMIT',f'{axis} {lo}~{hi} 밖으로 가려 해 멈췄습니다'
                break
            _command(bot,1 if axis == 'pan' else 2,target)
            pose[axis] = target
            moves += 1
            sleep_fn(SETTLE_SECONDS)
    except KeyboardInterrupt:
        status,reason = 'INTERRUPTED','Ctrl+C로 보정을 멈췄습니다'
    except Exception as exc:
        status,reason = 'ERROR',str(exc)
    result = dict(status=status,reason=reason,**pose,moves=moves,
                  response_px_per_degree=response,measurement=measured,correction=errors,events=events)
    if status == 'ALIGNED':
        path = Path(last_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        data = dict(schema_version=1,pan=pose['pan'],tilt=pose['tilt'],
                    response_px_per_degree=response,
                    saved_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                    reference_source_sha256=reference.get('source_sha256'),
                    vx_error_px=errors['dx_px'],height_error_px=errors['dy_px'])
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        temporary.replace(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--photo',type=Path,help='장치를 쓰지 않고 사진 한 장 측정')
    parser.add_argument('--pan',type=int,help='학교 시험의 현재 팬 명령 각도')
    parser.add_argument('--tilt',type=int,help='학교 시험의 현재 틸트 명령 각도')
    args = parser.parse_args()
    if args.photo is not None:
        measured = measure(cv2.imread(str(args.photo)))
        reference = json.loads(REFERENCE.read_text(encoding='utf-8'))
        print(json.dumps(dict(measurement=measured,correction=correction(measured,reference)),
                         ensure_ascii=False,indent=2))
        return
    answer = input('카메라 앞을 손으로 가리지 말고, 로봇을 START 차선 가운데에 놓았나요? (y/n) ')
    if answer.strip().lower() != 'y':
        print('중단했습니다. 서보·바퀴를 움직이지 않았습니다.')
        return
    saved = load_last()
    pose = _validate_pose(dict(pan=saved['pan'] if args.pan is None else args.pan,
                               tilt=saved['tilt'] if args.tilt is None else args.tilt))
    print(f"시작 명령 각도: 팬 {pose['pan']} · 틸트 {pose['tilt']}",flush=True)
    # 실물 준비 확인을 받은 직접 실행에서만 드라이버와 카메라를 연다.
    from Raspbot_Lib import Raspbot
    import importlib.util
    spec = importlib.util.spec_from_file_location('camera_align_video',ROOT/'missions/03_video.py')
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)
    camera = video.LatestCamera()
    try:
        camera.start()
        result = align(Raspbot(),camera,initial_pose=pose)
    finally:
        camera.close()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S_%f')
    (OUTPUT/f'align_{stamp}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    error = result['correction']
    details = f", 소실점 오차 {error['dx_px']:.1f}px · 높이 오차 {error['dy_px']:.1f}px" if error and error['reliable'] else ''
    print(f"{result['status']}: 팬 {result['pan']} · 틸트 {result['tilt']}{details} — {result['reason']}")


if __name__ == '__main__':
    main()
