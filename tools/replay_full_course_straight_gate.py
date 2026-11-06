#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 네번째주행 직진보정 범위
"""원본 재생, 같은 입력에서 guide_center만 끈 그림자 계산으로 원인 확인."""
import argparse,copy,csv,json
from pathlib import Path
import cv2
from replay_full_course_video import load,VideoCamera,SOURCE
WINDOWS=((8,10),(39,43))
def run(video,out,source=None):
    out.mkdir(parents=True,exist_ok=True);m=load('straight_gate',SOURCE.read_text() if source is None else source.read_text())
    camera=VideoCamera(video);c=m.LaneController();rows=[]
    try:
        while True:
            try:frame,index=camera.snapshot()
            except EOFError:break
            now=index/camera.fps;lines=m.find_lines(frame,c.previous,c.width)
            diagnosis=any(a<=now<b for a,b in WINDOWS)
            shadow=copy.deepcopy(c) if diagnosis else None
            if shadow is not None:
                shadow._route_center=lambda lines:None
                alternative=shadow.update(lines,now)
            else:alternative=None
            speeds=c.update(lines,now);r=c.report()
            row=dict(frame=index,seconds=now,state=r['state'],step=r['route_step'],left=r['left'],right=r['right'],
                 center=r['center'],guide=r['guide_center'],left_speed=speeds[0],right_speed=speeds[2],
                 crossing=lines['slow']['crossing_near'],window_until=r.get('front_guide_until'),
                 without_guide_left=None if alternative is None else alternative[0],without_guide_right=None if alternative is None else alternative[2],
                 corner=r['corner_direction'],corner_end=r['corner_end'],corner_ended_at=r['corner_ended_at'])
            rows.append(row)
            if diagnosis and speeds[0]==70 and speeds[2]==0 and index%3==0:
                image=m.lane.annotated(frame,r)
                cv2.putText(image,f"{now:.2f}s CENTER {r['center']} GUIDE {r['guide_center']}",(8,420),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
                cv2.imwrite(str(out/f'jump_{index:04d}.jpg'),image)
    finally:camera.close()
    with (out/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
    windows=[]
    for a,b in WINDOWS:
        rs=[r for r in rows if a<=r['seconds']<b]
        jumps=[r for r in rs if (r['left_speed'],r['right_speed'])==(70,0)]
        windows.append(dict(start=a,end=b,frames=len(rs),jump70_0=len(jumps),
            changed_without_guide=sum((r['without_guide_left'],r['without_guide_right'])!=(70,0) for r in jumps),
            strong_right=sum(r['left_speed']>=60 and r['right_speed']<=5 for r in rs),
            states=sorted(set(r['state'] for r in rs)),steps=sorted(set(r['step'] for r in rs))))
    summary=dict(frames=len(rows),windows=windows,step2_first=next((r['seconds'] for r in rows if r['step']==2),None))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path)
    a=p.parse_args();run(a.video,a.output,a.source)
