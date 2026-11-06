#!/usr/bin/env python3
# 지시서: specs/13-full-course.md ④
"""④의 시간·발 위치·스레드 분리를 실제 장치 없이 검증한다."""
import ast
import csv
import importlib.util
import io
import json
from pathlib import Path
import threading
import time
import unittest

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/full_course_safety'
spec=importlib.util.spec_from_file_location('safe_course_unit',ROOT/'missions/13_full_course.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def frame(left=100,right=540):
    image=np.full((480,640,3),60,np.uint8)
    for x in (left,right):
        if x is not None:cv2.line(image,(x,0),(x,479),(0,255,255),5)
    return image


def packet(found,sequence,now,image=None):
    return dict(found=found,sequence=sequence,captured_at=now,
                context=m.lane_context(frame() if image is None else image))


def person(x=320,y=220,score=.3):return ('person',score,(x-20,y-100,40,100))
def stop(height=50,score=.4):return ('stop sign',score,(200,100,50,height))


class SafetyTests(unittest.TestCase):
    def setUp(self):self.events=[]

    def tearDown(self):
        if self.events:
            (OUT/(self._testMethodName+'.json')).write_text(json.dumps(self.events,ensure_ascii=False,indent=2)+'\n')

    def clear(self):
        c=m.FullCourseController()
        for _ in range(3):c.observe_distance(40)
        return c

    def advance(self,c,found,now,sequence=None,lines=None,image=None):
        image=frame() if image is None else image
        lines=m.find_lines(image,c.previous,c.width) if lines is None else lines
        speeds=c.update(lines,now,packet(found,now if sequence is None else sequence,now,image))
        c.motor_sent(speeds,now)
        r=c.report()
        self.events.append(dict(seconds=now,state=r['state'],speeds=speeds,
                                route_step=r['route_step'],start_passes=r['start_passes'],
                                floor_color=r['floor_color'],slow_active=r['slow_active'],
                                paused_seconds=r['paused_seconds'],message=r['safety_message'],
                                people=r['person'],stop_until=r['stop_until'],ignore_until=r['ignore_until']))
        return speeds

    def test_original_algorithms_and_order_unchanged(self):
        original=ast.parse((OUT/'baseline_13.py.txt').read_text())
        current=ast.parse((ROOT/'missions/13_full_course.py').read_text())
        old={n.name:ast.dump(n) for n in original.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        new={n.name:ast.dump(n) for n in current.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name,value in old.items():self.assertEqual(value,new[name],name)

    def test_feet_not_head_or_anywhere_in_image(self):
        context=m.lane_context(frame())
        self.assertTrue(m.foot_on_lane(person()[2],context,440)['inside'])
        self.assertFalse(m.foot_on_lane(person(600)[2],context,440)['inside'])
        self.assertFalse(m.foot_on_lane(person(320,100)[2],context,440)['near'])
        self.assertFalse(m.foot_on_lane(person(320,120)[2],context,440)['near'])

    def test_one_boundary_uses_existing_07_width(self):
        for left,right in [(100,None),(None,540)]:
            point=m.foot_on_lane(person()[2],m.lane_context(frame(left,right)),440)
            self.assertEqual(point['basis'],'one_line_07_width')
            self.assertTrue(point['inside'])

    def test_person_above_visible_road_end_is_outside(self):
        image=np.full((480,640,3),150,np.uint8)
        image[80:160]=10
        cv2.line(image,(250,170),(100,479),(0,255,255),8)
        cv2.line(image,(390,170),(540,479),(0,255,255),8)
        context=m.lane_context(image)
        self.assertIsNotNone(context['road_top'])
        p=m.foot_on_lane(person(320,140)[2],context,440)
        self.assertEqual(p['offroad_reason'],'above_road_end')
        self.assertFalse(p['inside'])

    def test_current_vanishing_point_excludes_background_not_old_one(self):
        image=frame(None,None)
        cv2.line(image,(320,180),(100,479),(0,255,255),8)
        cv2.line(image,(320,180),(540,479),(0,255,255),8)
        context=m.lane_context(image)
        self.assertGreater(context['horizon'],140)
        p=m.foot_on_lane(person(320,140)[2],context,440)
        self.assertEqual(p['offroad_reason'],'above_vanishing_point')
        self.assertTrue(m.foot_on_lane(person()[2],m.lane_context(frame()),440,horizon=300)['inside'])

    def test_white_ground_excluded_black_track_and_partial_paint_kept(self):
        image=frame()
        image[222:234,300:341]=255
        p=m.foot_on_lane(person()[2],m.lane_context(image),440)
        self.assertEqual(p['offroad_reason'],'not_black_floor')
        self.assertFalse(p['inside'])
        image=frame()
        image[222:229,300:341]=255
        self.assertTrue(m.foot_on_lane(person()[2],m.lane_context(image),440)['inside'])
        # 화면 끝에 발이 걸쳐 밑 픽셀을 볼 수 없으면 제외하지 않는다.
        self.assertTrue(m.foot_on_lane(person(320,479)[2],m.lane_context(frame()),440)['inside'])

    def test_no_lines_uses_center_half_and_logs_basis(self):
        image=frame(None,None)
        for x,want in [(159,False),(160,True),(320,True),(480,True),(481,False)]:
            self.assertEqual(m.foot_on_lane(person(x)[2],m.lane_context(image))['inside'],want)
        c=self.clear()
        self.advance(c,[person()],0,image=image)
        self.assertEqual(self.advance(c,[person()],.1,image=image),m.lane.STOP)
        self.assertIn('선 없음-가운데 기준',c.report()['safety_message'])

    def test_two_hits_in_half_second_not_same_packet_twice(self):
        c=self.clear()
        self.advance(c,[person()],0,sequence=1)
        self.advance(c,[person()],.1,sequence=1)
        self.assertFalse(c.safety.signs.person)
        self.advance(c,[],.2,sequence=2)
        self.advance(c,[person()],.4,sequence=3)
        self.assertTrue(c.safety.signs.person)
        c=self.clear()
        self.advance(c,[person()],0)
        self.advance(c,[person()],.51)
        self.assertFalse(c.safety.signs.person)

    def test_confirmation_uses_capture_interval_with_processing_delay(self):
        c=self.clear()
        image=frame()
        for captured,completed in [(0.,.2),(.4,.6)]:
            p=packet([person()],captured,captured,image)
            speeds=c.update(m.find_lines(image,c.previous,c.width),completed,p)
            c.motor_sent(speeds,completed)
        self.assertTrue(c.safety.signs.person)

    def test_threshold_point3_and_one_second_clear(self):
        c=self.clear()
        self.advance(c,[person(score=.299)],0)
        self.advance(c,[person(score=.299)],.1)
        self.assertFalse(c.safety.signs.person)
        self.advance(c,[person()],.2)
        self.assertEqual(self.advance(c,[person()],.3),m.lane.STOP)
        self.advance(c,[person(600)],.5)
        self.assertEqual(self.advance(c,[person(600)],1.49),m.lane.STOP)
        self.assertNotEqual(self.advance(c,[person(600)],1.5),m.lane.STOP)

    def test_fifteen_seconds_latches_even_after_person_leaves(self):
        c=self.clear()
        self.advance(c,[person()],0)
        self.advance(c,[person()],.1)
        for i in range(2,153):self.advance(c,[person()],i/10)
        self.assertTrue(c.safety.person_locked)
        for i in range(153,180):self.advance(c,[],i/10)
        self.assertEqual(c.speeds,m.lane.STOP)
        self.assertEqual(c.report()['state'],'PERSON_CHECK15')

    def test_stale_results_are_discarded_not_person_absence(self):
        c=self.clear()
        self.advance(c,[person()],0)
        self.advance(c,[person()],.1)
        old=packet([],3,.2)
        c.update(m.find_lines(frame(),c.previous,c.width),1.,old)
        self.assertEqual(c.report()['state'],'STALEVISION')
        self.assertTrue(c.safety.signs.person)
        self.advance(c,[],1.1)
        self.assertTrue(c.safety.signs.person)

    def test_stop_size_confirmation_three_seconds_and_cooldown(self):
        c=self.clear()
        self.advance(c,[stop(height=38)],0)
        self.advance(c,[stop(height=38)],.1)
        self.assertFalse(c.safety.signs.stop_pending)
        self.advance(c,[stop()],.2)
        self.assertEqual(self.advance(c,[stop()],.3),m.lane.STOP)
        until=c.safety.signs.stop_until
        self.assertAlmostEqual(until,3.3)
        self.assertEqual(self.advance(c,[stop()],3.29),m.lane.STOP)
        self.assertNotEqual(self.advance(c,[stop()],3.3),m.lane.STOP)
        self.assertAlmostEqual(c.safety.signs.ignore_until,8.3)
        # 같은 표지 지속은06처럼 부재 확인 전까지 다시 세지 않는다.
        self.advance(c,[stop()],3.4)
        self.advance(c,[],3.5)
        for tick in range(36,81):self.advance(c,[],tick/10)
        self.advance(c,[stop()],8.1)
        self.assertNotEqual(self.advance(c,[stop()],8.2),m.lane.STOP)
        self.assertEqual(self.advance(c,[stop()],8.31),m.lane.STOP)

    def test_obstacle_median_error_and_recovery_use_04(self):
        s=m.SafetyController()
        states=[]
        for value in [40,40,40,24,24,24,36,36,36,None,None,None,40,40,40]:
            s.observe_distance(value)
            states.append((value,s.obstacle.moving,s.obstacle.invalid_count,s.obstacle.filtered_cm))
        self.assertTrue(states[2][1]);self.assertFalse(states[4][1]);self.assertTrue(states[7][1])
        self.assertEqual(states[11][2],3);self.assertFalse(states[11][1]);self.assertTrue(states[-1][1])
        (OUT/'fake_distance.json').write_text(json.dumps(states,indent=2)+'\n')

    def test_pause_freezes_route_start_color_and_all_hold_timers(self):
        c=self.clear()
        initial=m.find_lines(frame(),None,None)
        initial['floor']['color']='blue'
        self.advance(c,[],0,lines=initial)
        c.route.route_step=5
        c.route.start_passes=0
        c.route.choice='RIGHT';c.route.choice_since=0
        c.route.slow_seen_since=0;c.route.slow_end_since=0
        self.advance(c,[person()],.1,lines=initial)
        self.advance(c,[person()],.2,lines=initial)
        frozen=dict(c.route.__dict__)
        incoming=m.find_lines(frame(),c.previous,c.width)
        incoming['start']=dict(visible=True,near=True)
        incoming['floor']['color']='red'
        incoming['slow']['text']=True
        for i in range(3,90):self.advance(c,[person()],i/10,lines=incoming)
        self.assertEqual(c.route.__dict__,frozen)
        self.assertEqual(c.route.start_passes,0)
        self.assertEqual(c.route.floor_color,'blue')
        self.advance(c,[person(600)],9.,lines=incoming)
        self.advance(c,[person(600)],10.,lines=incoming)
        self.assertFalse(c.safety.blocked)
        self.assertLess(c.route_now,.5)
        self.assertFalse(c.route.stopped)

    def test_loop_logs_fallback_and_sends_zero_even_on_error(self):
        image=frame(None,None)
        class Camera:
            def snapshot(self):return image.copy(),1
        class Worker:
            def snapshot(self):return packet([person()],1,time.monotonic()-.01,image)
        sent=[]
        def send(speeds):
            sent.append(speeds)
            if len(sent)==1:raise RuntimeError('fake output failure')
        with self.assertRaisesRegex(RuntimeError,'fake output failure'):
            m.run_safety_loop(Camera(),Worker(),lambda:40,lambda:False,io.StringIO(),send)
        self.assertEqual(sent[-1],m.lane.STOP)
        stream=io.StringIO()
        def successful(speeds):sent.append(speeds)
        m.run_safety_loop(Camera(),Worker(),lambda:40,lambda:len(sent)>=3,stream,successful)
        self.assertIn('선 없음-가운데 기준',stream.getvalue())

    def test_vision_inference_runs_only_in_background(self):
        image=frame();lock=threading.Lock()
        class Camera:
            sequence=0
            def snapshot(self):
                with lock:return image.copy(),self.sequence
        class Detector:
            calls=[]
            def __call__(self,image):
                self.calls.append(threading.current_thread().name)
                if len(self.calls)>1:time.sleep(.2)
                return []
        camera=Camera();detector=Detector();worker=m.FullCourseVisionWorker(camera,detector).start()
        try:
            end=time.monotonic()+2
            while worker.snapshot() is None and time.monotonic()<end:time.sleep(.002)
            self.assertIsNotNone(worker.snapshot())
            c=m.FullCourseController(worker,require_distance=False)
            with lock:camera.sequence=1
            began=time.monotonic();times=[]
            while time.monotonic()-began<.15:
                lines=m.find_lines(image,c.previous,c.width)
                tic=time.perf_counter();speeds=c.update(lines,time.monotonic());times.append(time.perf_counter()-tic)
                c.motor_sent(speeds,time.monotonic());time.sleep(.005)
            self.assertGreater(len(times),5)
            self.assertLess(max(times),.05)
            self.assertTrue(all(name=='full-course-yolo320' for name in detector.calls))
            (OUT/'thread_timing.json').write_text(json.dumps(dict(iterations=len(times),
                max_update_ms=max(times)*1000,median_update_ms=float(np.median(times))*1000,
                detector_sleep_ms=200,detector_threads=detector.calls),indent=2)+'\n')
        finally:worker.close()


if __name__=='__main__':unittest.main(verbosity=2)
