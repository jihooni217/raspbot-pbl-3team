#!/usr/bin/env python3
# 지시서: specs/13-full-course.md 13번 먼 거리 입력 보정
"""장치 없는 실제 연결 반복으로 원시CSV/먼거리/오류/정지/복구를 확인한다."""
import csv
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/full_course_ultra_cap'
s=importlib.util.spec_from_file_location('cap_runtime_test',ROOT/'tools/test_full_course_runtime.py')
t=importlib.util.module_from_spec(s);s.loader.exec_module(t);m=t.m

class Tests(unittest.TestCase):
    def test_loop_raw_csv_far_errors_close_and_recovery(self):
        clock=t.Clock();camera=t.Camera();context=m.lane_context(camera.frame);rec=t.Recorder()
        class Vision:
            def snapshot(self):return dict(sequence=camera.seq,captured_at=clock.now,found=[],context=context)
        raw=[481]*5+[0]*3+[481]*3+[24]*3+[36]*3
        index=0;reports=[]
        def read():
            nonlocal index
            value=raw[min(index,len(raw)-1)];index+=1;return value
        def record(r):
            reports.append(dict(index=index,raw=r['raw_distance_cm'],state=r['safety_state'],
                median=r['distance_cm'],speeds=r['speeds'],errors=r['ultra_invalid_count']))
        stream=io.StringIO()
        with patch.object(m.time,'monotonic',clock.clock),patch.object(m.time,'sleep',clock.sleep),patch('builtins.print'):
            m.run_safety_loop(camera,Vision(),read,lambda:index>len(raw),stream,lambda speeds:None,
                              recorder=rec,on_report=record)
        states={}
        for r in reports:states[r['index']]=r
        self.assertEqual(states[3]['median'],400);self.assertFalse(states[3]['state']=='OBSTACLEWAIT')
        self.assertTrue(any(states[5]['speeds']))
        self.assertEqual(states[8]['state'],'ULTRA_ERROR');self.assertFalse(any(states[8]['speeds']))
        self.assertTrue(any(states[11]['speeds']))
        self.assertEqual(states[14]['state'],'OBSTACLEWAIT');self.assertFalse(any(states[14]['speeds']))
        self.assertTrue(any(states[17]['speeds']))
        rows=list(csv.DictReader(io.StringIO(stream.getvalue())))
        self.assertTrue(any(float(r['raw_ultra_cm'])==481 and float(r['ultra_cm'] or 0)==400 for r in rows))
        (OUT/'fake_scenario.csv').write_text(stream.getvalue())
        (OUT/'fake_scenario.json').write_text(json.dumps(states,ensure_ascii=False,indent=2)+'\n')
    def test_nonpositive_and_read_failure_remain_errors(self):
        for raw in (0,-1,None,float('inf'),float('nan')):
            safety=m.SafetyController()
            for _ in range(3):safety.observe_distance(40)
            for _ in range(3):safety.observe_distance(m.distance_for_obstacle(raw))
            self.assertEqual(safety.obstacle.invalid_count,3);self.assertFalse(safety.obstacle.moving)
        clock=t.Clock();camera=t.Camera();rec=t.Recorder();stream=io.StringIO()
        def fail():raise OSError('fake I2C read failure')
        reports=[]
        with patch.object(m.time,'monotonic',clock.clock),patch.object(m.time,'sleep',clock.sleep),patch('builtins.print'):
            m.run_safety_loop(camera,None,fail,lambda:clock.now>.2,stream,lambda speeds:None,
                              recorder=rec,on_report=lambda r:reports.append(dict(r)))
        self.assertGreaterEqual(reports[-1]['ultra_invalid_count'],3)
        self.assertIn('fake I2C',reports[-1]['distance_read_error'])
        self.assertIn('fake I2C',stream.getvalue())

if __name__=='__main__':unittest.main(verbosity=2)
