#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 유지 종료·재시작 시험
"""원본 전체를 카메라로 재생해 유지 시작/끝/금지시간과 흰바닥을 기록."""
import argparse
import csv
import json
from pathlib import Path
import cv2
from replay_full_course_video import VideoCamera,load,SOURCE

def run(video,out):
    out.mkdir(parents=True,exist_ok=True)
    m=load('corner_exit_video',SOURCE.read_text());controller=m.LaneController();camera=VideoCamera(video)
    rows=[];events=[];active=None;last_end=None
    try:
        while True:
            try:frame,index=camera.snapshot()
            except EOFError:break
            now=index/camera.fps;lines=m.find_lines(frame,controller.previous,controller.width)
            speeds=controller.update(lines,now);r=controller.report()
            rows.append(dict(frame=index,seconds=now,state=r['state'],route_step=r['route_step'],
                speeds=speeds,corner=r['corner_direction'],since=r['corner_since'],end=r['corner_ended_at'],
                reason=r['corner_end'],cooldown=r['corner_cooldown_until'],white_ratio=r['corner_white_ratio']))
            if r['corner_since'] is not None and active is None:
                active=dict(start=now,start_frame=index,direction=r['corner_direction'],route_step=r['route_step'],
                            gap_from_last_end=None if last_end is None else now-last_end)
                cv2.imwrite(str(out/f'start_{index:04d}.jpg'),frame)
            if r['corner_since'] is None and active is not None:
                active.update(end=now,end_frame=index,duration=now-active['start'],reason=r['corner_end'],
                              next_allowed=r['corner_cooldown_until'])
                events.append(active);active=None;last_end=now
                cv2.imwrite(str(out/f'end_{index:04d}.jpg'),frame)
    finally:camera.close()
    with (out/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
    if events:
        with (out/'events.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,events[0]);w.writeheader();w.writerows(events)
    summary=dict(video=str(video),frames=len(rows),fps=camera.fps,events=events,active_at_video_end=active,
        max_duration=max((e['duration'] for e in events),default=0),
        within_time_limit=all(e['duration']<=m.CORNER_LIMIT_SECONDS+1e-9 for e in events),
        cooldown_ok=all(e['gap_from_last_end'] is None or e['gap_from_last_end']>=m.CORNER_COOLDOWN_SECONDS-1e-9 for e in events),
        white_frames=sum(r['white_ratio']>m.CORNER_WHITE_RATIO for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    assert summary['within_time_limit'] and summary['cooldown_ok']

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.video,a.output)
