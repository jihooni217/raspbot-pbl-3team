#!/usr/bin/env python3
# 지시서: specs/14-camera-auto-align.md
"""저장 영상의 고른 장면을 재서 숫자 기준을 만든다. 장치 접근 없음."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT/'results/videos/blackbox_20261104_204945_297796_6c23c5b9.mp4')
    parser.add_argument('--frame', type=int, default=0, help='0부터 세는 디코딩 장면 번호')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('camera_align_reference',ROOT/'missions/14_camera_align.py')
    align = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(align)
    cap = cv2.VideoCapture(str(args.video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.set(cv2.CAP_PROP_POS_FRAMES,args.frame)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError('기준 장면을 읽지 못했습니다.')
    finally:
        cap.release()
    measured = align.measure(frame)
    if not measured['reliable']:
        raise RuntimeError(measured['reason'])
    digest = hashlib.sha256()
    with args.video.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024),b''):
            digest.update(block)
    reference = dict(schema_version=1, source_video=str(args.video.resolve().relative_to(ROOT)),
                     source_sha256=digest.hexdigest(), frame_index_zero_based=args.frame,
                     frame_number_one_based=args.frame+1, fps=fps, seconds=args.frame/fps,
                     frame_size=[640,480], nominal_pose=dict(pan=80,tilt=5),
                     selection_reason='START 글자와 두 직선 경계가 보이고 바퀴값0인 첫 화면. 노란 조향 덧그림이 없고 모서리/옆길 진입 전이다.',
                     vx_ref=measured['vx'], lane_top_ref=measured['lane_top'],
                     floor_top_ref=None, height_metric='lane_top', width_ref=measured['width'],
                     height_note='양쪽 fitted line 주변15px에서 노란 픽셀3개 이상이5행 연속 나타나는 최초 높이의 평균. 실제 바닥/벽 경계 분류값은 아니다.',
                     width_y=479, width_method='straight_boundary_extrapolation',
                     width_note='실제 맨 아래 두 선은 화면 밖이다. fitted line을 y479까지 연장한 폭이며 직접 관측한 두 픽셀 사이 폭이 아니다.',
                     pixels_per_degree_initial=10, servo_response_px_per_degree=None,
                     measurement=measured)
    align.OUTPUT.mkdir(parents=True,exist_ok=True)
    (align.REFERENCE).write_text(json.dumps(reference,ensure_ascii=False,indent=2)+'\n')
    cv2.imwrite(str(align.OUTPUT/'reference_frame.png'),frame)
    cv2.imwrite(str(align.OUTPUT/'reference_annotated.png'),align.annotated(frame,measured))
    print(json.dumps(reference,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
