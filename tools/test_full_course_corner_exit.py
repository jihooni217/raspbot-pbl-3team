#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 두번째주행 종료 보완
"""1.4초/0.15초/4초/흰섬 해제만 장치 없이 확인한다."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('old_corner_helpers',ROOT/'tools/test_full_course_corner.py')
t=importlib.util.module_from_spec(s);s.loader.exec_module(t);m=t.m

class Tests(unittest.TestCase):
    def test_limit_one_point4(self):
        c=t.controller()
        for i in range(14):self.assertEqual(c.update(t.lines(),i/10),(55,55,5,5))
        c.update(t.lines(),1.4)
        self.assertEqual(c.corner_end,'LIMIT1.4S');self.assertIsNone(c.corner_since)
        self.assertAlmostEqual(c.corner_cooldown_until,5.4)
    def test_early_not_horizontal_point15(self):
        c=t.controller();c.update(t.lines(),0)
        c.update(t.lines(horizontal=False),.1);c.update(t.lines(horizontal=False),.24)
        self.assertIsNotNone(c.corner_since)
        c.update(t.lines(horizontal=False),.25)
        self.assertEqual(c.corner_end,'NOT_HORIZONTAL_0.15S')
    def test_early_two_normal_lines_point15(self):
        c=t.controller();c.update(t.lines(),0)
        c.update(t.lines(100,570),.1);c.update(t.lines(100,570),.25)
        self.assertEqual(c.corner_end,'BOTH_NORMAL_0.15S')
    def test_four_second_lockout_even_after_rearm(self):
        c=t.controller();c.update(t.lines(),0)
        c.update(t.lines(horizontal=False),.1);c.update(t.lines(horizontal=False),.25)
        for i in range(3,43):
            c.update(t.lines(horizontal=bool(i%2)),i/10)
            self.assertIsNone(c.corner_since)
        c.update(t.lines(),4.25);self.assertIsNotNone(c.corner_since)
    def test_white_floor_ends_immediately_without_stop_or_recovery(self):
        c=t.controller();c.update(t.lines(),0)
        lines=t.lines();lines.update(corner_white_floor=True,corner_white_ratio=.85)
        speeds=c.update(lines,.1)
        self.assertEqual(c.corner_end,'WHITE_FLOOR');self.assertEqual(c.corner_ended_at,.1)
        self.assertFalse(c.stopped);self.assertTrue(any(speeds));self.assertIsNone(c.corner_since)
        self.assertEqual(c.report()['corner_white_ratio'],.85)
    def test_white_ratio_uses_real_bottom_and_ignores_black_padding(self):
        image=np.full((480,640,3),60,np.uint8);image[360:]=255
        self.assertEqual(m.corner_white_floor(image),1)
        image[280:]=0
        self.assertEqual(m.corner_white_floor(image),0)
    def test_tracks_original_shape_instead_of_other_horizontal_line(self):
        c=t.controller()
        original=dict(x=200,area=1000,span=500,rise=20,bbox=(0,0,500,20))
        lines=t.lines();lines['corner_traces']=[original];c.update(lines,0)
        vertical=dict(x=10,area=1000,span=20,rise=140,bbox=(0,0,20,140))
        other=dict(x=460,area=1000,span=350,rise=20,bbox=(280,100,350,20))
        lines=t.lines();lines['corner_traces']=[vertical,other]
        c.update(lines,.1);c.update(lines,.25)
        self.assertEqual(c.corner_end,'NOT_HORIZONTAL_0.15S')

if __name__=='__main__':unittest.main(verbosity=2)
