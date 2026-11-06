#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 세번째주행
"""고정시간/화면배정/이탈정지와진단회귀를장치없이검증한다."""
import ast
import importlib.util
from pathlib import Path
import unittest
import cv2
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('corner_helpers',ROOT/'tools/test_full_course_corner.py')
t=importlib.util.module_from_spec(s);s.loader.exec_module(t);m=t.m

class Tests(unittest.TestCase):
    def test_fixed_hold_ignores_both_early_conditions(self):
        c=t.controller();c.update(t.lines(),0)
        for i in range(1,13):self.assertEqual(c.update(t.lines(100,570,False),i/10),(55,55,5,5))
        c.update(t.lines(100,570,False),1.3)
        self.assertEqual(c.corner_end,'FIXED1.3S');self.assertIsNone(c.previous);self.assertTrue(c.reacquiring)
        self.assertAlmostEqual(c.corner_cooldown_until,5.3)
    def test_screen_single_labels_discard_old_assignment(self):
        for x,name in ((319,'left'),(320,'right'),(400,'right')):
            c=t.controller();c._end_corner(0,'test');c.previous=dict(left=x,right=x+470)
            c.update(t.lines(x,None,False),.1)
            self.assertEqual(c.lines[name],x);self.assertIsNone(c.lines['right' if name=='left' else 'left'])
            self.assertIsNone(c.previous)
    def test_real_two_lines_more_than_half_second_restore(self):
        c=t.controller();c._end_corner(0,'test')
        for now in (.1,.4,.6):
            c.update(t.lines(100,570,False),now);self.assertTrue(c.reacquiring)
        c.update(t.lines(100,570,False),.61)
        self.assertFalse(c.reacquiring);self.assertIsNotNone(c.previous)
    def test_fragment_straight_override_cannot_replace_right_single(self):
        c=t.controller();c._end_corner(0,'test')
        cap=cv2.VideoCapture(str(ROOT/'results/videos/raw_20261105_121100_390693.mp4'))
        cap.set(cv2.CAP_PROP_POS_MSEC,11800);ok,frame=cap.read();cap.release();self.assertTrue(ok)
        speeds=c.update(m.find_lines(frame,c.previous,c.width),.1)
        self.assertIsNone(c.lines['left']);self.assertIsNotNone(c.lines['right'])
        self.assertIsNone(c.guide_center);self.assertLess(speeds[0],speeds[2])
    def test_white_immediate_end_then_half_second_latched_stop(self):
        c=t.controller();c.update(t.lines(),0)
        white=t.lines();white.update(corner_white_ratio=.8,corner_white_floor=True)
        c.update(white,.1);self.assertEqual(c.corner_end,'WHITE_FLOOR');self.assertFalse(c.stopped)
        c.update(white,.4);self.assertFalse(c.stopped)
        self.assertEqual(c.update(white,.6),m.lane.STOP);self.assertTrue(c.stopped)
        self.assertEqual(c.state,'LANE_DEPARTURE')
        c.update(t.lines(horizontal=False),.7);self.assertEqual(c.state,'LANE_DEPARTURE')
    def test_ratio_boundary_and_interrupted_timer(self):
        c=t.controller()
        for now in (0,.4,.8):
            x=t.lines(100,570,False);x['corner_white_ratio']=.6;c.update(x,now)
        self.assertFalse(c.stopped)
        c=t.controller()
        for now,ratio in [(0,.8),(.3,.8),(.4,.5),(.5,.8),(.9,.8)]:
            x=t.lines(100,570,False);x['corner_white_ratio']=ratio;c.update(x,now)
        self.assertFalse(c.stopped)
        x['corner_white_ratio']=.8;c.update(x,1.);self.assertEqual(c.state,'LANE_DEPARTURE')
    def test_departure_wall_clock_also_checked_while_safety_paused(self):
        c=m.FullCourseController(require_distance=False)
        x=t.lines(100,570,False);x.update(corner_white_ratio=.8,corner_white_floor=True)
        c.update(x,0);self.assertTrue(c.safety.blocked)
        c.update(x,.5)
        self.assertTrue(c.stopped);self.assertEqual(c.speeds,m.lane.STOP)
        self.assertEqual(c.report()['state'],'LANE_DEPARTURE');self.assertEqual(c.report()['safety_message'],'차선 벗어남')
    def test_existing_other_judgments_unchanged(self):
        p=ROOT/'results/full_course_corner_reacquire/before_13.py.txt'
        nodes=[]
        for text in (p.read_text(),Path(m.__file__).read_text()):
            tree=ast.parse(text);nodes.append({n.name:ast.dump(n) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))})
        for name in ('find_floor_color','find_slow_markers','find_start_markers','find_lane_dividers','SafetyController','MotorOutput','distance_for_obstacle'):
            self.assertEqual(nodes[0][name],nodes[1][name],name)

if __name__=='__main__':unittest.main(verbosity=2)
