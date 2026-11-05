#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 세번째주행 선 재배정/이탈 정지
"""저장 원본으로 유지와 종료후 선 이름·바퀴값을 기록. 장치 접근 없음."""
import argparse,csv,json
from pathlib import Path
import cv2
from replay_full_course_video import VideoCamera,load,SOURCE

def run(video,out,source=None,limit=None):
    out.mkdir(parents=True,exist_ok=True)
    m=load('reacquire_video',SOURCE.read_text() if source is None else source.read_text())
    c=m.LaneController();camera=VideoCamera(video);rows=[];events=[];active=None
    try:
        while True:
            try:frame,index=camera.snapshot()
            except EOFError:break
            now=index/camera.fps
            if limit is not None and now>=limit:break
            observed=m.find_lines(frame,c.previous,c.width);speeds=c.update(observed,now);r=c.report()
            row=dict(frame=index,seconds=now,state=r['state'],step=r['route_step'],left=r['left'],right=r['right'],
                 width=r['width'],speeds=speeds,left_speed=speeds[0],right_speed=speeds[2],corner=r.get('corner_direction'),
                 corner_since=r.get('corner_since'),corner_end=r.get('corner_end'),ended_at=r.get('corner_ended_at'),
                 reacquiring=r.get('reacquiring',False),white_ratio=r.get('corner_white_ratio'),stopped=r['stopped'])
            rows.append(row)
            if r.get('corner_since') is not None and active is None:active=dict(start=now,step=r['route_step'])
            if r.get('corner_since') is None and active is not None:
                active.update(end=now,duration=now-active['start'],reason=r.get('corner_end'));events.append(active);active=None
            if 11.6<=now<=12.6 and index%3==0:
                marked=m.lane.annotated(frame,r)
                cv2.putText(marked,f"{now:.2f}s LEFT {r['left']} RIGHT {r['right']}",(8,410),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
                cv2.putText(marked,f"{speeds} {r['state']}",(8,440),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
                cv2.imwrite(str(out/f'diagnosis_{index:04d}.jpg'),marked)
    finally:camera.close()
    with (out/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
    windows=[]
    for event in events:
        window=[r for r in rows if event['end']<=r['seconds']<event['end']+1]
        windows.append(dict(event=event,post_second=window))
    result=dict(video=str(video),frames=len(rows),events=events,post_windows=windows,
                stop=next((r for r in rows if r['stopped']),None),active_at_end=active)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(video=str(video),frames=len(rows),events=events,stop=result['stop']),ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--limit',type=float)
    a=p.parse_args();run(a.video,a.output,a.source,a.limit)
