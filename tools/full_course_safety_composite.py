#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ④ 시험3
"""실제 영상의 표지를 그대로 복사한 사진. 실제 YOLO, 장치 접근 없음."""
import csv
import json
import time
from pathlib import Path
import cv2
from full_course_safety_test import m,Camera,wait_result,clear_distance,packet

OUT=Path('results/full_course_safety/composite')
OUT.mkdir(parents=True,exist_ok=True)
cap=cv2.VideoCapture('results/videos/blackbox_20261104_214713_354784_1c79a793.mp4')
cap.set(cv2.CAP_PROP_POS_FRAMES,31)
ok,base=cap.read();cap.release()
assert ok
# 영상31장의 실제 person상자400,20,43,113 둘레4px 포함. 크기/색/모양 변경 없음.
crop=base[16:137,396:447].copy()
images={}
for label,x in [('inside',295),('outside',530)]:
    image=base.copy();image[22:143,x:x+51]=crop
    images[label]=image
    cv2.imwrite(str(OUT/f'{label}.png'),image)
camera=Camera(images['inside'])
worker=m.FullCourseVisionWorker(camera,clock=camera.clock).start()
found={}
try:
    for i,(label,image) in enumerate(images.items()):
        camera.set(image,i,i*.1)
        result=wait_result(worker,i)
        found[label]=result['found']
finally:worker.close()
(OUT/'detections.json').write_text(json.dumps(found,indent=2)+'\n')
print(json.dumps(found),flush=True)
c=m.FullCourseController();clear_distance(c)
rows=[]
for i in range(16):
    now=i/10
    label='inside' if i<3 else 'outside'
    image=images[label]
    speeds=c.update(m.find_lines(image,c.previous,c.width),now,packet(image,found[label],i,now))
    c.motor_sent(speeds,now)
    report=c.report()
    rows.append(dict(seconds=now,image=label,state=report['state'],speeds=speeds,
                     route_step=report['route_step'],paused_seconds=report['paused_seconds'],
                     people=report['person']))
    if i in (1,3,12,13):cv2.imwrite(str(OUT/f'result_{i:02d}.jpg'),m.safety_annotated(image,report))
with (OUT/'timeline.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
summary=dict(stopped_at=next((r['seconds'] for r in rows if r['state']=='PERSONWAIT'),None),
             outside_since=.3,resumed_at=next((r['seconds'] for r in rows if r['seconds']>=.3 and r['state'].startswith('TRACK')),None),
             source_frame=31,crop=[396,16,51,121],inside_paste=[295,22],outside_paste=[530,22])
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary),flush=True)
assert summary['stopped_at']==.1,summary
assert summary['resumed_at']==1.3,summary
