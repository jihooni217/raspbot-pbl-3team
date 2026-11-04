#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ④
"""저장 사진/영상과 가짜 거리만 사용한다. 로봇 장치를 열지 않는다."""
import argparse
import ast
import csv
import importlib.util
import json
from pathlib import Path
import threading
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/full_course_safety'
spec = importlib.util.spec_from_file_location('course_safety_test',ROOT/'missions/13_full_course.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Camera:
    def __init__(self,frame,sequence=0,now=0.):
        self.lock = threading.Lock()
        self.frame,self.sequence,self.now = frame,sequence,now
    def set(self,frame,sequence,now):
        with self.lock:self.frame,self.sequence,self.now = frame,sequence,now
    def snapshot(self):
        with self.lock:return self.frame.copy(),self.sequence
    def clock(self):
        with self.lock:return self.now


def wait_result(worker,sequence):
    end = time.monotonic()+5
    while time.monotonic()<end:
        result = worker.snapshot()
        if result is not None and result['sequence']==sequence:return result
        time.sleep(.002)
    raise RuntimeError(f'YOLO 결과5초 대기 초과: {sequence}')


def cache(source,path,start=0,end=None,photos=False):
    """시험에서만 매 장면의 추론 완료를 기다려 누락 없는 증거를 저장한다."""
    cap = None
    if photos:
        files = sorted(source.glob('*.jpg'))
        count,fps = len(files),10.
        def read(index):
            raw = cv2.imread(str(files[index]))
            frame = np.zeros_like(raw);frame[:280] = raw[200:]
            return frame
    else:
        cap = cv2.VideoCapture(str(source))
        count,fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),cap.get(cv2.CAP_PROP_FPS)
        cap.set(cv2.CAP_PROP_POS_FRAMES,start)
        def read(index):
            ok,frame = cap.read()
            if not ok:raise RuntimeError(f'영상 읽기 실패: {index}')
            return frame
    end = min(count,count if end is None else end)
    first = read(start)
    camera = Camera(first,start,start/fps)
    worker = m.FullCourseVisionWorker(camera,clock=camera.clock).start()
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('a',encoding='utf-8') as stream:
            for index in range(start,end):
                frame = first if index==start else read(index)
                camera.set(frame,index,index/fps)
                began = time.monotonic()
                packet = wait_result(worker,index)
                row = dict(index=index,seconds=index/fps,found=packet['found'],
                           inference_wait_seconds=time.monotonic()-began,source=str(source))
                stream.write(json.dumps(row)+'\n');stream.flush()
                if (index-start)%100==0:print(f'추론 {index}/{end}',flush=True)
    finally:
        worker.close()
        if cap is not None:cap.release()
    print(f'추론 저장: {start}~{end-1} {path}',flush=True)


def load_cache(path):
    rows = {}
    for line in path.read_text().splitlines():
        row = json.loads(line);rows[row['index']] = row
    return rows


def packet(frame,found,sequence,now):
    return dict(sequence=sequence,captured_at=now,completed_at=now,found=found,context=m.lane_context(frame))


def clear_distance(controller):
    for _ in range(3):controller.observe_distance(40)


def replay(source,cache_path,output,photos=False):
    detected = load_cache(cache_path)
    cap = None
    if photos:
        files = sorted(source.glob('*.jpg'));count,fps = len(files),10.
        def read(i):
            raw = cv2.imread(str(files[i]));frame = np.zeros_like(raw);frame[:280]=raw[200:];return frame
    else:
        cap = cv2.VideoCapture(str(source));count,fps=int(cap.get(7)),cap.get(5)
        def read(i):
            ok,frame=cap.read()
            if not ok:raise RuntimeError(f'영상 읽기 실패{i}')
            return frame
    assert sorted(detected)==list(range(count)),f'추론 기록 부족: {len(detected)}/{count}'
    controller = m.FullCourseController()
    clear_distance(controller)
    stops = []
    people = 0
    timings = []
    baseline = m.LaneController()
    identical = True
    output.mkdir(parents=True,exist_ok=True)
    try:
        with (output/'replay.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream)
            writer.writerow(('frame','seconds','route_step','start_passes','state','speeds','person','stop_boxes',
                             'distance_cm','safety_message','paused_seconds','baseline_speeds'))
            for i in range(count):
                frame=read(i);now=i/fps
                lines=m.find_lines(frame,controller.previous,controller.width)
                clear_distance(controller)
                vision=packet(frame,detected[i]['found'],i,now)
                began=time.perf_counter();speeds=controller.update(lines,now,vision);timings.append(time.perf_counter()-began)
                controller.motor_sent(speeds,now)
                report=controller.report();people+=len(report['person'])
                if report['blocked']:stops.append(dict(frame=i,reason=report['state'],person=report['person']))
                reference=baseline.update(m.find_lines(frame,baseline.previous,baseline.width),now) if photos else None
                if photos and speeds!=reference:identical=False
                writer.writerow((i,now,report['route_step'],report['start_passes'],report['state'],speeds,
                                 json.dumps(report['person'],ensure_ascii=False),json.dumps(report['stop_boxes']),
                                 report['distance_cm'],report['safety_message'],report['paused_seconds'],reference))
                if report['person'] and (i%20==0 or report['blocked']):
                    cv2.imwrite(str(output/f'person_{i:04d}.jpg'),m.safety_annotated(frame,report))
                # 정상 FINISH는④정지와별도다. 기존사진도구의재시작동작에맞춰비교한다.
                if photos and baseline.stopped:baseline=m.LaneController()
                if photos and controller.stopped:
                    controller=m.FullCourseController();clear_distance(controller)
    finally:
        if cap is not None:cap.release()
    summary=dict(frames=count,person_observations=people,safety_stop_frames=len(stops),
                 stops=stops,identical_to_legacy=identical if photos else None,
                 update_median_ms=float(np.median(timings))*1000,
                 update_p95_ms=float(np.percentile(timings,95))*1000)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('cache','replay'))
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--photos',action='store_true')
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--end',type=int)
    args=parser.parse_args()
    if args.mode=='cache':cache(args.source,args.cache,args.start,args.end,args.photos)
    else:
        if args.output is None:parser.error('replay에는--output이필요합니다')
        replay(args.source,args.cache,args.output,args.photos)


if __name__=='__main__':main()
