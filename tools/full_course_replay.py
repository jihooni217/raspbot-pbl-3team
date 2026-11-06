#!/usr/bin/env python3
# 지시서: specs/13-full-course.md
"""장치를 열지 않고 저장 사진으로 13번의 경로 선택 근거를 기록한다."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.home() / 'train_raw/lap_211306')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fps', type=float, default=10, help='사진을 재생하는 초당 장수')
    args = parser.parse_args()
    if args.fps <= 0:
        parser.error('--fps는 양수여야 합니다.')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'results'):
        parser.error('--output은 results 아래로 정해 주세요.')
    output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('full_course_replay', ROOT / 'missions/13_full_course.py')
    course = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(course)
    controller = course.LaneController()
    previous = None
    events = []
    stops = 0
    files = sorted(args.source.glob('*.jpg'))
    if not files:
        raise RuntimeError(f'재생할 사진이 없습니다: {args.source}')
    with (output / 'replay.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = ('photo', 'seconds', 'route_step', 'route_leg', 'choice', 'choice_end', 'crossings', 'start_passes',
                  'base_speed', 'speeds', 'left', 'right', 'width', 'guide_center',
                  'text', 'roundabout', 'crossing', 'state', 'stopped')
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for i, path in enumerate(files):
            image = cv2.imread(str(path))
            if image is None:
                raise RuntimeError(f'사진 읽기 실패: {path}')
            # 지정 사진 시험의 t5와 동일한 입력 보정. 주행 코드에는 이 변환이 없다.
            frame = np.zeros_like(image)
            frame[:280] = image[200:]
            lines = course.find_lines(frame, controller.previous, controller.width)
            controller.update(lines, i / args.fps)
            report = controller.report()
            marks = lines['slow']
            row = {name: report[name] for name in fields if name in report}
            row.update(photo=path.name, seconds=i / args.fps,
                       text=marks['text'], roundabout=marks['roundabout_near'],
                       crossing=marks['crossing_near'])
            writer.writerow(row)
            current = (report['route_step'], report['choice'], report['choice_end'], report['stopped'])
            if current != previous:
                event = dict(photo=path.name, seconds=i / args.fps,
                             route_step=report['route_step'], choice=report['choice'],
                             choice_end=report['choice_end'], stopped=report['stopped'],
                             start_passes=report['start_passes'])
                events.append(event)
                marked = course.lane.annotated(frame, report)
                cv2.putText(marked, f"STEP {report['route_step']} {report['route_leg']} CHOICE {report['choice']}",
                            (8, 390), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,255,255), 1)
                guide = report['guide_center']
                if guide is not None:
                    cv2.line(marked, (round(guide),120), (round(guide),279), (255,0,255), 2)
                cv2.imwrite(str(output / f'event_{path.stem}.jpg'), marked)
                previous = current
            if controller.stopped:
                if report['state'] != 'FINISH':
                    stops += 1
                    controller = course.LaneController()
    summary = dict(events=events, unexpected_stops=stops, frame_count=len(files),
                   finished=controller.state == 'FINISH', start_passes=controller.start_passes)
    (output / 'events.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
