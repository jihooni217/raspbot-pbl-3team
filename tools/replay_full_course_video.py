#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤
"""원본 영상 카메라로 순서/차선 판단을 재생한다. 장치·모터·실시간 대기 없음."""
import argparse
import csv
import json
from pathlib import Path
import types
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'missions/13_full_course.py'

def load(name,text):
    module=types.ModuleType(name);module.__file__=str(SOURCE)
    exec(compile(text,str(SOURCE),'exec'),module.__dict__);return module

class VideoCamera:
    def __init__(self,path):
        self.cap=cv2.VideoCapture(str(path));self.fps=self.cap.get(cv2.CAP_PROP_FPS)
        if not self.cap.isOpened() or self.fps<=0:raise RuntimeError(f'영상 열기 실패: {path}')
        self.sequence=-1
    def snapshot(self):
        ok,frame=self.cap.read()
        if not ok:raise EOFError
        self.sequence+=1;return frame,self.sequence
    def close(self):self.cap.release()

def replay(module,path,out,start,end,stop_after):
    camera=VideoCamera(path);controller=module.LaneController();rows=[]
    try:
        while True:
            try:frame,index=camera.snapshot()
            except EOFError:break
            now=index/camera.fps
            if stop_after is not None and now>=stop_after:break
            lines=module.find_lines(frame,controller.previous,controller.width)
            speeds=controller.update(lines,now);r=controller.report()
            left,right=lines['left'],lines['right']
            row=dict(frame=index,seconds=now,route_step=r['route_step'],state=r['state'],choice=r['choice'],
                left_speed=speeds[0],right_speed=speeds[2],steering=speeds[0]-speeds[2],
                observed_width=None if left is None or right is None else abs(right-left),width=r['width'],
                width_rejected=r.get('width_rejected',False),corner=r.get('corner_direction'),
                corner_end=r.get('corner_end'),front_corner=lines.get('front_corner',False))
            rows.append(row)
            if start<=now<end and (index%15==0):
                marked=module.lane.annotated(frame,r)
                cv2.putText(marked,f"{now:.2f}s STEP {r['route_step']} STEER {row['steering']} CORNER {row['corner']}",
                            (8,410),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
                cv2.imwrite(str(out/f'frame_{index:04d}.jpg'),marked)
    finally:camera.close()
    with (out/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
    segment=[r for r in rows if start<=r['seconds']<end];signs=[int(np.sign(r['steering'])) for r in segment if r['steering']]
    summary=dict(window_seconds=[start,end],frames=len(segment),
        sign_flips=sum(a!=b for a,b in zip(signs,signs[1:])),mean_steering=float(np.mean([r['steering'] for r in segment])),
        right_frames=sum(r['steering']>0 for r in segment),left_frames=sum(r['steering']<0 for r in segment),
        zero_frames=sum(r['steering']==0 for r in segment),
        corner_frames=sum(bool(r['corner']) for r in segment),
        width_min=min((r['width'] for r in segment if r['width'] is not None),default=None))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(out,json.dumps(summary),flush=True)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True)
    p.add_argument('--before',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--start',type=float,default=12);p.add_argument('--end',type=float,default=15)
    p.add_argument('--stop-after',type=float);a=p.parse_args()
    if not 0<=a.start<a.end:p.error('0 <= start < end 필요')
    if a.stop_after is not None and a.stop_after<a.end:p.error('stop-after는end이상')
    result={}
    for name,text in ([('before',a.before.read_text())] if a.before else [])+[('after',SOURCE.read_text())]:
        out=a.output/name;out.mkdir(parents=True,exist_ok=True)
        result[name]=replay(load('video_'+name,text),a.video,out,a.start,a.end,a.stop_after)
    (a.output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
