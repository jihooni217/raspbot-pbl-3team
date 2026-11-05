#!/usr/bin/env python3
# 지시서: specs/13-full-course.md 실제 주행 입구
"""모터 재전송/최종3회/키/Ctrl+C/오류/check를 가짜 장치로 확인한다."""
import ast
from contextlib import contextmanager,redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/full_course_runtime'
s=importlib.util.spec_from_file_location('runtime_course',ROOT/'missions/13_full_course.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class Clock:
    now=0.
    def clock(self):return self.now
    def sleep(self,seconds):self.now+=max(0,seconds)
class Bot:
    def __init__(self,clock):self.clock=clock;self.calls=[];self.ultra=[]
    def Ctrl_Muto(self,n,v):self.calls.append((self.clock.now,n,v))
    def Ctrl_Ulatist_Switch(self,value):self.ultra.append(value)
    def read_data_array(self,reg,n):return [1 if reg==0x1b else 144]
class Recorder:
    paths={}
    def __init__(self,*args):self.closed=False
    def start(self):return self
    def update(self,report):pass
    def check(self):pass
    def close(self):self.closed=True
class Camera:
    def __init__(self):
        self.frame=np.full((480,640,3),60,np.uint8);self.seq=0
        for x in (100,540):cv2.line(self.frame,(x,0),(x,479),(0,255,255),6)
    def start(self):return self
    def snapshot(self):self.seq+=1;return self.frame.copy(),self.seq
    def close(self):pass

class Tests(unittest.TestCase):
    def setUp(self):self.clock=Clock();self.bot=Bot(self.clock)
    def output(self,check=False):return m.MotorOutput(self.bot,check,clock=self.clock.clock,sleep_fn=self.clock.sleep)
    def test_same_values_refresh_at_point2_and_limit80(self):
        motor=self.output();speeds=(200,-200,100,-100)
        motor(speeds);self.assertEqual([v for t,n,v in self.bot.calls],[80,-80,80,-80])
        self.clock.now=.19;motor(speeds);self.assertEqual(len(self.bot.calls),4)
        self.clock.now=.2;motor(speeds);self.assertEqual(len(self.bot.calls),8)
        self.assertEqual(self.bot.calls[4][0],.2)
        self.clock.now=.24;motor((30,30,30,30));self.assertEqual(len(self.bot.calls),12)
    def test_close_exactly_three_batches_idempotent(self):
        motor=self.output();motor.close();motor.close()
        self.assertEqual([(n,v) for t,n,v in self.bot.calls],[(n,0) for n in range(4)]*3)
        self.assertAlmostEqual(self.bot.calls[4][0]-self.bot.calls[0][0],.2)
        self.assertAlmostEqual(self.bot.calls[8][0]-self.bot.calls[4][0],.2)
    def test_stop_attempts_every_wheel_after_error(self):
        original=self.bot.Ctrl_Muto
        def fail(n,v):
            original(n,v)
            if n==0:raise OSError('fake I2C failure')
        self.bot.Ctrl_Muto=fail
        with self.assertRaisesRegex(RuntimeError,'정지 실패'):self.output().close()
        self.assertEqual(len(self.bot.calls),12)
    def test_check_sends_no_commands_even_zero_or_close(self):
        motor=self.output(True);motor((80,80,80,80));motor(m.lane.STOP);motor.close()
        self.assertEqual(self.bot.calls,[])
    def run_loop_case(self,mode):
        camera=Camera();clock=self.clock;motor=self.output();rec=Recorder();before_stop=[]
        context=m.lane_context(camera.frame)
        class Vision:
            def snapshot(self):return dict(sequence=camera.seq,captured_at=clock.now,found=[],context=context)
        original=m.FullCourseController
        class Controller(original):
            @property
            def stopped(self):return super().stopped or (mode=='finish' and clock.now>=.65)
        def keys():
            if mode=='finish' or clock.now<.65:return False
            if mode=='ctrlc':raise KeyboardInterrupt
            if mode=='error':raise RuntimeError('fake runtime failure')
            return True
        def stop():before_stop.append(len(self.bot.calls));motor.close()
        with patch.object(m,'FullCourseController',Controller),patch.object(m.time,'monotonic',clock.clock),patch.object(m.time,'sleep',clock.sleep),redirect_stdout(io.StringIO()):
            try:
                result=m.run_safety_loop(camera,Vision(),lambda:40,keys,io.StringIO(),motor,recorder=rec,on_stop=stop)
                self.assertIn(mode,('key','finish'))
            except KeyboardInterrupt:self.assertEqual(mode,'ctrlc')
            except RuntimeError as exc:self.assertEqual(mode,'error');self.assertIn('fake runtime',str(exc))
        self.assertTrue(rec.closed);self.assertEqual(len(before_stop),1)
        self.assertEqual(len(self.bot.calls)-before_stop[0],12)
        self.assertEqual([(n,v) for t,n,v in self.bot.calls[-12:]],[(n,0) for n in range(4)]*3)
        return dict(mode=mode,total_motor_commands=len(self.bot.calls),shutdown_motor_commands=12)
    def test_key_normal_final_three(self):self.run_loop_case('key')
    def test_finish_normal_final_three(self):self.run_loop_case('finish')
    def test_ctrlc_final_three(self):self.run_loop_case('ctrlc')
    def test_error_final_three(self):self.run_loop_case('error')
    def test_cli_check_full_fake_run_no_motor(self):
        clock=self.clock;bot=self.bot
        class Vision:
            inference_count=0
            def __init__(self,camera):self.camera=camera;self.context=m.lane_context(camera.frame)
            def start(self):return self
            def close(self):pass
            def snapshot(self):
                self.inference_count+=1
                return dict(sequence=self.camera.seq,captured_at=clock.now,found=[],context=self.context)
        @contextmanager
        def keys():yield lambda:False
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            driver=types.SimpleNamespace(Raspbot=lambda:bot)
            with patch('builtins.input',return_value='y'),patch.dict(sys.modules,{'Raspbot_Lib':driver}),patch.object(m,'__file__',str(Path(temp)/'missions/13_full_course.py')),patch.object(m,'prepare_camera',return_value=dict(pan=85,tilt=3,source='fake')),patch.object(m.lane.video,'LatestCamera',Camera),patch.object(m,'FullCourseVisionWorker',Vision),patch.object(m,'FullCourseRecorder',Recorder),patch.object(m.obstacles,'keyboard_stop',keys),patch.object(m.time,'monotonic',clock.clock),patch.object(m.time,'sleep',clock.sleep),redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['--check','--seconds','.7']),0)
            result=json.loads(next((Path(temp)/'results').glob('full_course_*.json')).read_text())
            self.assertEqual(result['reason'],'0.7초 경과');self.assertEqual(result['motor_commands'],0)
            self.assertEqual(bot.calls,[]);self.assertEqual(bot.ultra,[1,0])
    def test_judgment_functions_and_thresholds_unchanged(self):
        old=ast.parse((OUT/'before_13.py.txt').read_text());new=ast.parse(Path(m.__file__).read_text())
        a={n.name:ast.dump(n) for n in old.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        b={n.name:ast.dump(n) for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name,value in a.items():
            if name not in ('run_safety_loop','FullCourseVisionWorker'):self.assertEqual(value,b[name],name)
    def test_metrics_finish_excludes_cleanup_and_later_inferences(self):
        vision=types.SimpleNamespace(inference_count=0)
        with patch.object(m.time,'monotonic',self.clock.clock),patch.object(m,'cpu_temperature',return_value=40):
            monitor=m.RuntimeMonitor(vision,True)
            self.clock.now=20;vision.inference_count=100;monitor.finish()
            self.clock.sleep(4);vision.inference_count=200
            result=monitor.summary()
        self.assertEqual(result['seconds'],20);self.assertEqual(result['yolo_frames'],100)

    def test_printed_i2c_error_is_failure(self):
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'I2C error'):
            m.checked_driver_call(lambda:print('I2C error: fake'))

if __name__=='__main__':unittest.main(verbosity=2)
