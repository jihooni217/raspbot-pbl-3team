#!/usr/bin/env python3
# 지시서: specs/13-full-course.md
"""장치 없는 13번 경로 선택·속도·정지 회귀 검증."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('course_test', ROOT/'missions/13_full_course.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def observation():
    return dict(left=100., right=540., left_count=100, right_count=100,
                traces=[dict(x=100., left_guide=70., right_guide=130.),
                        dict(x=540., left_guide=510., right_guide=570.)],
                slow=dict(text=False, crossing_near=False, roundabout_near=False),
                start=dict(visible=False, near=False), floor=dict(color=None), dividers=[])


class CourseTests(unittest.TestCase):
    def test_original_recognizers_unchanged(self):
        old = subprocess.check_output(['git','show','6360995:missions/13_full_course.py'],
                                      cwd=ROOT, text=True)
        new = (ROOT/'missions/13_full_course.py').read_text()
        for name in ('find_floor_color', 'find_slow_markers'):
            nodes = [next(n for n in ast.parse(source).body
                          if isinstance(n, ast.FunctionDef) and n.name == name)
                     for source in (old,new)]
            self.assertEqual(ast.dump(nodes[0]), ast.dump(nodes[1]))

    def test_mark_is_counted_once_and_rearms(self):
        event = m.MarkEvent()
        self.assertFalse(event.update(True, 0))
        self.assertFalse(event.update(True, .1))
        self.assertTrue(event.update(True, .2))
        self.assertFalse(event.update(True, .3))
        event.update(False, .4)
        event.update(False, .8)
        self.assertTrue(event.latched)
        event.update(False, .91)
        self.assertFalse(event.latched)
        self.assertFalse(event.update(True, 1))
        self.assertTrue(event.update(True, 1.21))

    def test_opposite_trace_does_not_change_selected_steering(self):
        for direction in ('RIGHT','LEFT'):
            outputs = []
            for shift in (0,50):
                c = m.LaneController()
                c.update(observation(), 0)
                c.route_step = 3
                c._choose(direction, 0)
                data = observation()
                opposite = 0 if direction == 'RIGHT' else 1
                for key in ('x','left_guide','right_guide'):
                    data['traces'][opposite][key] += shift
                outputs.append(c.update(data, .1))
            self.assertEqual(*outputs)
            self.assertGreater(outputs[0][0], outputs[0][2]) if direction == 'RIGHT' else self.assertLess(outputs[0][0], outputs[0][2])

    def test_real_both_lines_required_for_stable_exit(self):
        c = m.LaneController()
        c.update(observation(), 0)
        c.route_step = 3
        c._choose('RIGHT', 0)
        for i in range(1,7):
            c.update(observation(), i/10)
        self.assertEqual(c.choice, 'RIGHT')
        c.update(observation(), .71)
        self.assertIsNone(c.choice)
        self.assertEqual(c.choice_end, 'BOTH_STABLE')

    def test_fragments_of_one_line_do_not_count_as_both(self):
        c = m.LaneController()
        c.update(observation(), 0)
        c.route_step = 3
        c._choose('RIGHT', 0)
        data = observation()
        data['traces'][0]['x'] = 300
        data['traces'][1]['x'] = 330
        for i in range(1,10):
            c.update(data, i/10)
        self.assertEqual(c.choice, 'RIGHT')

    def test_new_mark_does_not_restart_four_second_limit(self):
        c = m.LaneController()
        c.update(observation(), 0)
        c.route_step = 3
        c._choose('RIGHT', 0)
        data = observation()
        data['traces'] = data['traces'][1:]
        data['slow']['crossing_near'] = True
        for i in range(1,40):
            c.update(data, i/10)
        self.assertEqual(c.choice_since, 0)
        self.assertEqual(c.choice, 'RIGHT')
        c.update(data, 4.)
        self.assertIsNone(c.choice)
        self.assertEqual(c.choice_end, 'LIMIT4S')

    def test_route_turn_keeps_mean_slow_speed_and_limit(self):
        c = m.LaneController()
        c.update(observation(), 0)
        c.route_step = 3
        c._choose('RIGHT', 0)
        wheels = c.update(observation(), .1)
        self.assertEqual(sum(wheels)/4,25)
        self.assertTrue(all(0 <= v <= 80 for v in wheels))

    def test_color_speeds_and_release_are_preserved(self):
        c = m.LaneController()
        c.route_step = 10
        for now,color,expected in [(0,'blue',45),(.1,'red',25),(.2,None,25),(.6,None,25),(.71,None,35)]:
            data = observation()
            data['floor']['color'] = color
            self.assertEqual(c.update(data,now),(expected,)*4)

    def test_line_loss_stops_during_choice(self):
        c = m.LaneController()
        c.update(observation(), 0)
        c.route_step = 3
        c._choose('RIGHT', 0)
        c.update(observation(), .1)
        data = observation()
        data.update(left=None,right=None,traces=[])
        for i in range(2,13):
            c.update(data,i/10)
        self.assertTrue(c.stopped)
        self.assertEqual(c.speeds,m.lane.STOP)

    def test_stale_frame_stops_during_choice(self):
        c = m.LaneController()
        c.update(observation(),0)
        c._choose('RIGHT',0)
        self.assertEqual(c.tick(.51),m.lane.STOP)
        self.assertTrue(c.stopped)

    def test_departure_start_is_ignored(self):
        c = m.LaneController()
        data = observation()
        data['start'] = dict(visible=True,near=True)
        for i in range(10):
            c.update(data,i/10)
        self.assertEqual(c.start_passes,0)
        self.assertFalse(c.stopped)

    def test_first_start_continues_and_second_latches_stop(self):
        c = m.LaneController()
        c.route_step = 5
        data = observation()
        data['start'] = dict(visible=True,near=True)
        for i in range(3):
            c.update(data,i/10)
        self.assertEqual(c.start_passes,1)
        self.assertFalse(c.stopped)
        for i in range(3,10):
            c.update(observation(),i/10)
        c.route_step = 12
        for i in range(10,13):
            c.update(data,i/10)
        self.assertEqual(c.start_passes,2)
        self.assertEqual(c.state,'FINISH')
        self.assertEqual(c.update(observation(),1.3),m.lane.STOP)

    def test_start_shape_positive_and_negative_photos(self):
        for index,expected in [(1040,True),(1790,True),(0,False),(660,False),(1320,False)]:
            image = cv2.imread(str(Path.home()/f'train_raw/lap_211306/{index:04d}.jpg'))
            self.assertIsNotNone(image)
            frame = np.zeros_like(image)
            frame[:280] = image[200:]
            self.assertEqual(m.find_start_markers(frame)['visible'],expected)

    def test_right_lane_uses_middle_of_white_and_right_yellow(self):
        c = m.LaneController()
        c.route_step = 5
        data = observation()
        data['dividers'] = [dict(x=200.,y=200.,area=500.)]
        c.update(data,0)
        self.assertEqual(c.guide_center,370.)

    def test_white_wall_foot_is_not_a_lane_divider(self):
        for index in (953,954):
            image = cv2.imread(str(Path.home()/f'train_raw/lap_211306/{index:04d}.jpg'))
            frame = np.zeros_like(image)
            frame[:280] = image[200:]
            self.assertEqual(m.find_lane_dividers(frame),[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
