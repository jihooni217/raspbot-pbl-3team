#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤
"""정상폭 기억/가상선의 구분/유지 방향/종료를 장치 없이 검증."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('corner_course',ROOT/'missions/13_full_course.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def lines(left=100,right=None,horizontal=True):
    return dict(left=left,right=right,left_count=1000 if left is not None else 0,right_count=800 if right is not None else 0,
                traces=[dict(x=x,area=1000 if i==0 else 800,left_guide=x-20,right_guide=x+20) for i,x in enumerate(v for v in (left,right) if v is not None)],front_corner=horizontal)

def controller():
    c=m.LaneController();c.width=470;c.previous=dict(left=100,right=570);c.normal_widths.extend([470]*15)
    return c

class Tests(unittest.TestCase):
    def test_collapse_rejected_and_normal_width_unchanged(self):
        c=controller()
        for i,width in enumerate((229,278,240,122)):
            c.update(lines(200,200+width,False),i/10)
            self.assertTrue(c.lines['width_rejected']);self.assertIsNone(c.lines['right'])
            self.assertEqual(c.width,470);self.assertEqual(list(c.normal_widths),[470]*15)
            self.assertEqual(c.previous['right']-c.previous['left'],470)
    def test_single_side_identity_does_not_switch_to_stale_other_side(self):
        c=controller()
        for i,x in enumerate((250,320,380,440,480)):
            observed=m.lane.assign_lines([(x,1500)],c.previous,c.width)
            observed.update(traces=[],front_corner=False)
            c.update(observed,i/10)
            self.assertIsNotNone(c.lines['left']);self.assertIsNone(c.lines['right'])
    def test_hold_cannot_reverse_for_three_seconds(self):
        c=controller()
        for i in range(30):
            observed=lines(100,None) if i%2==0 else lines(None,540)
            self.assertEqual(c.update(observed,i/10),(55,55,5,5))
        c.update(lines(),3.)
        self.assertIsNone(c.corner_since);self.assertEqual(c.corner_end,'LIMIT3S')
        c.update(lines(),3.1);self.assertIsNone(c.corner_since)
    def test_only_real_two_lines_can_end_after_point3(self):
        c=controller();c.update(lines(),0)
        c.update(lines(100,570,False),.1);c.update(lines(100,570,False),.2)
        self.assertIsNotNone(c.corner_since)
        c.update(lines(100,570,False),.4)
        self.assertIsNone(c.corner_since);self.assertEqual(c.corner_end,'BOTH_NORMAL_0.3S')
    def test_forks_roundabouts_and_active_choice_excluded(self):
        for step in (3,4,6,7):
            c=controller();c.route_step=step
            if step==6:c.second_crossings=0
            c.update(lines(),0);self.assertIsNone(c.corner_direction)
        c=controller();c._choose('RIGHT',0);c.update(lines(),.1)
        self.assertIsNone(c.corner_direction)
    def test_left_direction_supported(self):
        c=controller();c.route_step=2
        with patch.dict(m.CORNER_DIRECTIONS,{2:'LEFT'}):self.assertEqual(c.update(lines(),0),(5,5,55,55))
    def test_horizontal_geometry_and_missing_line_stop_have_priority(self):
        image=np.full((480,640,3),60,np.uint8)
        cv2.line(image,(20,180),(620,185),(0,255,255),8)
        self.assertTrue(m.find_lines(image)['front_corner'])
        c=controller();c.update(lines(),0)
        c.update(lines(None,None,False),.1)
        c.update(lines(None,None,False),.5)
        c.update(lines(None,None,False),.9)
        self.assertEqual(c.update(lines(None,None,False),1.1),m.lane.STOP)
        self.assertTrue(c.stopped)

if __name__=='__main__':unittest.main(verbosity=2)
