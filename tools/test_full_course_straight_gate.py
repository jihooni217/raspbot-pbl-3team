#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ⑤ 네번째주행 경로1 보정
"""직진보정의시간/실제양쪽선/단계한정및중복전환을장치없이검증."""
import ast,importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('gate_helpers',ROOT/'tools/test_full_course_corner.py')
t=importlib.util.module_from_spec(s);s.loader.exec_module(t);m=t.m

def observations(crossing=False):
    result=t.lines(100,570,False);result['slow']=dict(crossing_near=crossing)
    return result

class Tests(unittest.TestCase):
    def test_no_crossing_uses_normal_center_even_two_lines(self):
        c=t.controller();c.update(observations(),0)
        self.assertIsNone(c.guide_center);self.assertFalse(c.front_guide_active)
    def test_crossing_near_through_one_second_after_last_seen(self):
        c=t.controller();c.update(observations(True),0)
        self.assertEqual(c.guide_center,350)
        for now in (.25,.5,.75,1.):
            c.update(observations(False),now);self.assertEqual(c.guide_center,350)
        c.update(observations(False),1.01)
        self.assertIsNone(c.guide_center);self.assertFalse(c.front_guide_active)
    def test_new_visible_frame_extends_window(self):
        c=t.controller();c.update(observations(True),0);c.update(observations(True),.2)
        self.assertAlmostEqual(c.front_guide_until,1.2)
    def test_single_line_cannot_use_two_raw_fragments(self):
        c=t.controller();obs=observations(True);obs.update(left=None,right=400,left_count=0,right_count=1000)
        c.update(obs,0)
        self.assertTrue(c.front_guide_active);self.assertIsNone(c.guide_center)
        self.assertLess(c.center,320);self.assertLess(c.speeds[0],c.speeds[2])
    def test_end_step_one_sets_two_but_never_increments_other_steps(self):
        for old,expected in [(1,2),(2,2),(3,3),(5,5)]:
            c=t.controller();c.route_step=old;c._end_corner(2.,'FIXED1.3S')
            self.assertEqual(c.route_step,expected);self.assertFalse(c.front_guide_active)
    def test_other_route_straight_guides_and_choices_unchanged(self):
        for step in (3,6):
            c=t.controller();c.route_step=step
            self.assertEqual(c._route_center(observations()),350)
        c=t.controller();c.choice='RIGHT'
        self.assertEqual(c._route_center(observations()),590)
    def test_other_judgments_unchanged(self):
        before=ROOT/'results/full_course_straight_gate/before_13.py.txt'
        nodes=[]
        for text in (before.read_text(),Path(m.__file__).read_text()):
            tree=ast.parse(text);nodes.append({n.name:ast.dump(n) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))})
        for name in ('find_lines','find_floor_color','find_slow_markers','find_start_markers','find_lane_dividers','SafetyController','FullCourseController','MotorOutput','distance_for_obstacle'):
            self.assertEqual(nodes[0][name],nodes[1][name],name)

if __name__=='__main__':unittest.main(verbosity=2)
