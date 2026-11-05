#!/usr/bin/env python3
# 지시서: specs/13-full-course.md 실제/사진 표시 영역 통일
"""저장 블랙박스의 표시 검출 구간만 비교. 카메라/로봇 장치 접근 없음."""
import csv
import importlib.util
import json
from pathlib import Path
import types
import cv2

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/full_course_viewport'
SOURCE=ROOT/'missions/13_full_course.py'

def load(name,source):
    module=types.ModuleType(name);module.__file__=str(SOURCE)
    exec(compile(source,str(SOURCE),'exec'),module.__dict__)
    return module

before=load('viewport_before',(OUT/'before_13.py.txt').read_text())
after=load('viewport_after',SOURCE.read_text())
FEATURES=('crossing','roundabout','blue','red','slow','start')

def compare(path):
    cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS)
    rows=[];samples=[];index=0
    dest=OUT/path.stem;dest.mkdir(exist_ok=True)
    previous={version:False for version in ('before','after')}
    while True:
        ok,frame=cap.read()
        if not ok:break
        for version,module in [('before',before),('after',after)]:
            lines=module.find_lines(frame);mark=lines['slow'];color=lines['floor']['color']
            flags=dict(crossing=mark['crossing_near'],roundabout=mark['roundabout_near'],
                       blue=color=='blue',red=color=='red',slow=mark['text'],start=lines['start']['visible'])
            rows.append(dict(frame=index,seconds=index/fps,version=version,**flags))
            if flags['roundabout'] and not previous[version]:
                image=frame.copy()
                for x,y,w,h in mark['boxes']['roundabouts']:
                    cv2.rectangle(image,(x,y),(x+w,y+h),(0,0,255),2)
                cv2.putText(image,f'{version.upper()} ROUNDABOUT frame {index}',(8,470),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),1)
                name=f'{version}_roundabout_{index:04d}.jpg';cv2.imwrite(str(dest/name),image)
                samples.append(dict(version=version,frame=index,seconds=index/fps,boxes=mark['boxes']['roundabouts'],image=str(dest/name)))
            previous[version]=flags['roundabout']
        index+=1
    cap.release()
    with (dest/'frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
    intervals=[]
    for version in ('before','after'):
        selected=[r for r in rows if r['version']==version]
        for feature in FEATURES:
            first=None
            for r in selected+[dict(frame=index,**{feature:False})]:
                if r[feature] and first is None:first=r['frame']
                if not r[feature] and first is not None:
                    intervals.append(dict(version=version,feature=feature,first_frame=first,last_frame=r['frame']-1,
                                          start_seconds=first/fps,end_seconds=r['frame']/fps,frames=r['frame']-first))
                    first=None
    with (dest/'intervals.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,intervals[0]);w.writeheader();w.writerows(intervals)
    result=dict(video=str(path),fps=fps,frames=index,intervals=intervals,roundabout_samples=samples)
    (dest/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    for path in sorted((ROOT/'results/videos').glob('blackbox_20261104_*.mp4')):
        if '204945' in path.name or '214713' in path.name:compare(path)
