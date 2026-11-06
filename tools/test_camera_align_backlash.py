#!/usr/bin/env python3
# 지시서: specs/14-camera-auto-align.md (2026-11-05 실물 유격 보강)
"""장치 없이 실제 사진12장과 유격/시작 전송/한계/저장을 검증한다."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('align_photo_trials',ROOT/'tools/test_camera_align.py')
old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
m=old.align
REF=old.REFERENCE

class Bot:
    def __init__(self):
        self.commands=[];self.pose=dict(pan=80,tilt=5);self.actual=dict(self.pose)
        self.direction={};self.slack={}
    def Ctrl_Servo(self,servo,angle):
        axis='pan' if servo==1 else 'tilt'
        assert m.LIMITS[axis][0]<=angle<=m.LIMITS[axis][1]
        self.commands.append((servo,angle))
        delta=angle-self.pose[axis]
        if delta:
            direction=1 if delta>0 else -1
            if direction!=self.direction.get(axis):self.slack[axis]=2
            self.direction[axis]=direction
            if self.slack[axis]:self.slack[axis]-=1
            else:self.actual[axis]+=delta
        self.pose[axis]=angle

class Trials(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.last=Path(self.tmp.name)/'last.json';self.bot=Bot();self.waits=[]
    def run_case(self,features,initial=None):
        test=self
        class Camera:
            sequence=0
            def snapshot(self):
                self.sequence+=1
                test.assertEqual(test.bot.commands[:6],[(1,80)]*3+[(2,5)]*3)
                return self.sequence,self.sequence
        def measure(sequence):
            dx,dy=features(sequence)
            return dict(reliable=True,vx=REF['vx_ref']+dx,lane_top=REF['lane_top_ref']+dy)
        with patch.object(m,'measure',side_effect=measure):
            result=m.align(self.bot,Camera(),reference=REF,last_path=self.last,sleep_fn=self.waits.append,initial_pose=initial)
        self.assertEqual(len(self.bot.commands),6+result['moves']*3)
        for i in range(0,len(self.bot.commands),3):self.assertEqual(self.bot.commands[i:i+3],[self.bot.commands[i]]*3)
        prior=dict(pan=80,tilt=5)
        for servo,angle in self.bot.commands[6::3]:
            axis='pan' if servo==1 else 'tilt';self.assertEqual(abs(angle-prior[axis]),1);prior[axis]=angle
        return result
    def test_already_aligned_initial_send_then_one_second(self):
        r=self.run_case(lambda n:(0,0));self.assertEqual(r['status'],'ALIGNED');self.assertEqual(r['moves'],0)
        self.assertEqual(self.waits,[.02,.02,.02,.02,1.])
        self.assertEqual(json.loads(self.last.read_text())['vx_error_px'],0)
    def test_probe_accumulates_and_correction_tolerates_reverse_slack(self):
        for target in (83,77):
            self.bot=Bot();self.last.unlink(missing_ok=True)
            r=self.run_case(lambda n:((self.bot.actual['pan']-target)*10,0))
            self.assertEqual(r['status'],'ALIGNED');self.assertGreaterEqual(r['moves'],3)
            self.assertGreater(r['response_px_per_degree']['pan'],0)
            self.assertLessEqual(abs(r['correction']['dx_px']),10)
    def test_tilt_probe_and_negative_direction(self):
        r=self.run_case(lambda n:(0,(self.bot.actual['tilt']-8)*-10))
        self.assertEqual(r['status'],'ALIGNED');self.assertLess(r['response_px_per_degree']['tilt'],0)
    def test_five_degrees_without_response_only_then_unreliable(self):
        r=self.run_case(lambda n:(30,0));self.assertEqual(r['status'],'UNRELIABLE_RESPONSE')
        self.assertEqual(r['moves'],5);self.assertFalse(self.last.exists())
    def test_exactly_five_pixels_is_not_enough(self):
        r=self.run_case(lambda n:(30+min(len(self.bot.commands[6:])//3,5),0))
        self.assertEqual(r['status'],'UNRELIABLE_RESPONSE');self.assertEqual(r['moves'],5)
    def test_twenty_moves_reports_best_without_restore_or_save(self):
        original=json.dumps(dict(pan=80,tilt=5,response_px_per_degree=dict(pan=10,tilt=10)))
        self.last.write_text(original)
        r=self.run_case(lambda n:((40 if n==1 else 20 if n==3 else (30 if n%2 else -30)),0))
        self.assertEqual(r['status'],'MAX_MOVES');self.assertEqual(r['moves'],20)
        self.assertEqual(r['best']['move'],2);self.assertEqual(r['best']['correction']['dx_px'],20)
        self.assertEqual(self.last.read_text(),original)
    def test_thirteen_restore_uses_three_transmissions(self):
        pose=m.restore_saved_pose(self.bot,path=self.last,sleep_fn=self.waits.append)
        self.assertEqual(self.bot.commands,[(1,80)]*3+[(2,5)]*3)
        self.assertEqual(self.waits,[.02,.02,.3,.02,.02,.3])
        self.assertEqual(pose['source'],'default')
    def test_small_learned_slope_can_be_loaded(self):
        self.last.write_text(json.dumps(dict(pan=80,tilt=5,response_px_per_degree=dict(pan=1.2,tilt=-1.3))))
        self.assertEqual(m.load_last(self.last)['response_px_per_degree']['pan'],1.2)
    def test_actual_photos_and_no_motor_calls(self):
        self.assertEqual(json.loads((m.OUTPUT/'photo_trial.json').read_text())['passed'],12)
        self.assertNotIn('Ctrl_Muto(',Path(m.__file__).read_text())

if __name__=='__main__':
    old.photo_trial()
    unittest.main(verbosity=2)
