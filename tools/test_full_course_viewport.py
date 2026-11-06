#!/usr/bin/env python3
# 지시서: specs/13-full-course.md 실제/사진 표시 영역 통일
"""원본 분리와 녹화 오류 시 정지/해제를 장치 없이 확인한다."""
import ast
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/full_course_viewport'
s=importlib.util.spec_from_file_location('viewport_course',ROOT/'missions/13_full_course.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class Camera:
    def __init__(self,frame):self.frame=frame
    def snapshot(self):return self.frame.copy(),1

class Tests(unittest.TestCase):
    def test_mask_copy_lane_original_and_four_marker_inputs(self):
        frame=np.full((480,640,3),60,np.uint8);frame[280:]=(0,0,255)
        prior=frame.copy()
        with patch.object(m.lane,'find_lines',wraps=m.lane.find_lines) as lane:
            spies=[patch.object(m,name,wraps=getattr(m,name)) for name in
                   ('find_floor_color','find_slow_markers','find_start_markers','find_lane_dividers')]
            calls=[p.start() for p in spies]
            try:
                m.find_lines(frame)
                self.assertIs(lane.call_args.args[0],frame)
                for call in calls:
                    image=call.call_args.args[0]
                    self.assertIsNot(image,frame);self.assertTrue(np.array_equal(image[:280],frame[:280]))
                    self.assertFalse(np.any(image[280:]))
            finally:
                for spy in spies:spy.stop()
        self.assertTrue(np.array_equal(frame,prior))
        self.assertEqual(m.lane_context(frame)['height'],m.MARKER_VISIBLE_HEIGHT)
        self.assertTrue(np.array_equal(frame,prior))
    def test_mark_functions_thresholds_and_route_unchanged(self):
        before=ast.parse((OUT/'before_13.py.txt').read_text());after=ast.parse(Path(m.__file__).read_text())
        old={n.name:ast.dump(n) for n in before.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        new={n.name:ast.dump(n) for n in after.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name in ('find_floor_color','find_slow_markers','find_start_markers','find_lane_dividers','LaneController','MarkEvent'):
            self.assertEqual(old[name],new[name],name)
    def test_yolo_receives_original_and_context_uses_mask(self):
        frame=np.full((480,640,3),60,np.uint8);frame[280:]=(0,0,255)
        captured=[]
        def detector(image):captured.append(image.copy());return []
        worker=m.FullCourseVisionWorker(Camera(frame),detector).start()
        try:
            limit=time.monotonic()+3
            while worker.snapshot() is None and time.monotonic()<limit:time.sleep(.005)
            self.assertIsNotNone(worker.snapshot())
            self.assertTrue(np.array_equal(captured[0],frame))
            self.assertEqual(worker.snapshot()['context']['height'],280)
        finally:worker.close()
    def test_raw_exact_and_both_writers_closed(self):
        frame=np.full((480,640,3),60,np.uint8);writers=[]
        class Writer:
            def __init__(self,path,*args):self.path=path;self.frames=[];self.closed=False;writers.append(self)
            def isOpened(self):return True
            def write(self,image):
                self.frames.append(image.copy())
                if 'blackbox_' in self.path:recorder.stop.set()
            def release(self):self.closed=True
        recorder=m.FullCourseRecorder(Camera(frame),writer_factory=Writer).start()
        recorder.thread.join(3);recorder.close()
        self.assertEqual(recorder.saved_frames,1)
        self.assertTrue(np.array_equal(writers[0].frames[0],frame))
        self.assertFalse(np.array_equal(writers[1].frames[0],frame))
        self.assertTrue(all(w.closed for w in writers))
    def test_record_error_closes_writers(self):
        writers=[]
        class Writer:
            def __init__(self,*args):self.closed=False;writers.append(self)
            def isOpened(self):return len(writers)<2
            def release(self):self.closed=True
        recorder=m.FullCourseRecorder(Camera(np.zeros((480,640,3),np.uint8)),writer_factory=Writer).start()
        recorder.thread.join(3)
        with self.assertRaisesRegex(RuntimeError,'녹화 오류'):recorder.close()
        self.assertTrue(all(w.closed for w in writers))
    def test_loop_sends_zero_on_record_error(self):
        class Recorder:
            closed=False
            def start(self):return self
            def check(self):raise RuntimeError('test recorder failure')
            def close(self):self.closed=True
        rec=Recorder();sent=[]
        with self.assertRaisesRegex(RuntimeError,'test recorder failure'):
            m.run_safety_loop(None,None,lambda:40,lambda:False,io.StringIO(),sent.append,recorder=rec)
        self.assertEqual(sent[-1],m.lane.STOP);self.assertTrue(rec.closed)
    def test_actual_h264_pair_with_fake_camera(self):
        folder=ROOT/'results/videos';folder.mkdir(exist_ok=True)
        frame=np.tile(np.arange(640,dtype=np.uint16)%150+30,(480,1)).astype(np.uint8)
        frame=np.repeat(frame[:,:,None],3,axis=2)
        with tempfile.TemporaryDirectory(prefix='viewport_codec_test_',dir=folder) as directory:
            recorder=m.FullCourseRecorder(Camera(frame),output_dir=directory).start()
            until=time.monotonic()+3
            while recorder.saved_frames<4 and recorder.error is None and time.monotonic()<until:time.sleep(.01)
            recorder.close();counts=[]
            for kind,path in recorder.paths.items():
                cap=cv2.VideoCapture(str(path));self.assertTrue(cap.isOpened())
                self.assertEqual(cap.get(cv2.CAP_PROP_FPS),15)
                counts.append(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
                ok,image=cap.read();self.assertTrue(ok);self.assertEqual(image.shape,frame.shape)
                if kind=='raw':self.assertLess(float(np.mean(np.abs(image.astype(float)-frame))),5)
                cap.release()
            self.assertGreaterEqual(counts[0],4);self.assertEqual(counts[0],counts[1])
            (OUT/'codec_pair.json').write_text(json.dumps(dict(codec='avc1',fps=15,frames_per_file=counts,
                      fake_camera=True,temporary_videos_removed=True),indent=2)+'\n')

if __name__=='__main__':unittest.main(verbosity=2)
