#!/usr/bin/env python3
# 지시서: specs/14-camera-auto-align.md
"""집 시험: 실제 장치 없이12장 이동 사진과 가짜 서보의 보정/한계를 검증."""
import ast
from contextlib import redirect_stdout
import csv
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('camera_align_test',ROOT/'missions/14_camera_align.py')
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
REFERENCE = json.loads(align.REFERENCE.read_text())
IMAGE = cv2.imread(str(align.OUTPUT/'reference_frame.png'))


def shifted(dx=0,dy=0):
    return cv2.warpAffine(IMAGE,np.float32([[1,0,dx],[0,1,dy]]),(640,480),
                          flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)


def photo_trial():
    out = align.OUTPUT/'shifts'
    out.mkdir(exist_ok=True)
    rows,tiles = [],[]
    for axis in ('x','y'):
        for pixels in (-30,-20,-10,10,20,30):
            frame = shifted(pixels if axis == 'x' else 0,pixels if axis == 'y' else 0)
            name = f'{axis}_{pixels:+d}.png'
            cv2.imwrite(str(out/name),frame)
            # 저장한 PNG를 다시 읽어 평가한다.
            frame = cv2.imread(str(out/name))
            measured = align.measure(frame)
            change = align.correction(measured,REFERENCE)
            expected = ('RIGHT' if pixels > 0 else 'LEFT') if axis == 'x' else ('DOWN' if pixels > 0 else 'UP')
            key = 'pan_view' if axis == 'x' else 'tilt_view'
            amount_key = key+'_degrees'
            other_key = 'tilt_view_degrees' if axis == 'x' else 'pan_view_degrees'
            actual = change.get(key)
            amount = change.get(amount_key,999)
            amount_error = abs(amount - pixels/10)
            passed = (change['reliable'] and actual == expected and amount_error <= 1
                      and abs(change[other_key]) <= 1)
            rows.append(dict(photo=name,axis=axis,shift_px=pixels,expected=expected,observed=actual,
                             expected_degrees=pixels/10,estimated_degrees=round(amount,4),
                             error_degrees=round(amount_error,4),aligned_within_10px=change.get('aligned'),passed=passed))
            marked = align.annotated(frame,measured)
            tile = np.zeros((270,320,3),np.uint8)
            tile[:240] = cv2.resize(marked,(320,240))
            cv2.putText(tile,f'{axis.upper()} {pixels:+d}px {actual} {abs(amount):.2f}deg '+('PASS' if passed else 'FAIL'),
                        (4,260),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,255,0) if passed else (0,0,255),1)
            tiles.append(tile)
            print(f'{name:12} {actual:5} {amount:+.3f}deg error {amount_error:.3f} '+('PASS' if passed else 'FAIL'),flush=True)
    with (align.OUTPUT/'photo_trial.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream,rows[0].keys());writer.writeheader();writer.writerows(rows)
    summary = dict(passed=sum(row['passed'] for row in rows),total=len(rows),
                   max_amount_error_degrees=max(row['error_degrees'] for row in rows),
                   servo_sign_tested=False,hardware_moved=False,rows=rows)
    (align.OUTPUT/'photo_trial.json').write_text(json.dumps(summary,indent=2)+'\n')
    cv2.imwrite(str(align.OUTPUT/'photo_trial_contact.png'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,12,3)]))
    if summary['passed'] != 12:
        raise AssertionError(f"사진 방향 {summary['passed']}/12")
    return summary


class FakeBot:
    def __init__(self,pan=80,tilt=5):
        self.pose = dict(pan=pan,tilt=tilt)
        self.commands = []

    def Ctrl_Servo(self,servo,angle):
        axis = 'pan' if servo == 1 else 'tilt'
        lo,hi = align.LIMITS[axis]
        assert lo <= angle <= hi
        self.commands.append((servo,angle))
        self.pose[axis] = angle


class FakeCamera:
    def __init__(self,bot,target=None,response=None):
        self.bot = bot
        self.target = target or dict(pan=83,tilt=8)
        self.response = response or dict(pan=10,tilt=-10)
        self.sequence = 0

    def snapshot(self):
        self.sequence += 1
        dx = (self.bot.pose['pan'] - self.target['pan']) * self.response['pan']
        dy = (self.bot.pose['tilt'] - self.target['tilt']) * self.response['tilt']
        return shifted(dx,dy),self.sequence


class AlignTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='unit_',dir=align.OUTPUT)
        self.addCleanup(self.folder.cleanup)
        self.last = Path(self.folder.name)/'last.json'

    def run_align(self,bot,camera,**kwargs):
        return align.align(bot,camera,last_path=self.last,reference=REFERENCE,
                           sleep_fn=lambda seconds:None,**kwargs)

    def seed(self,pan=80,tilt=5,response=None):
        data = dict(pan=pan,tilt=tilt,response_px_per_degree=response or dict(pan=10,tilt=10))
        self.last.write_text(json.dumps(data))

    def test_reference_and_twelve_photo_directions(self):
        measured = align.measure(IMAGE)
        self.assertTrue(measured['reliable'])
        self.assertGreater(measured['width'],640)
        self.assertTrue(measured['width_extrapolated'])
        self.assertTrue(align.correction(measured,REFERENCE)['aligned'])
        result = json.loads((align.OUTPUT/'photo_trial.json').read_text())
        self.assertEqual(result['passed'],12)
        self.assertLessEqual(result['max_amount_error_degrees'],1)

    def test_missing_and_one_sided_lanes_do_not_move(self):
        images = [np.zeros_like(IMAGE),IMAGE.copy()]
        images[1][:,:320] = 0
        for frame in images:
            bot = FakeBot()
            class Camera:
                def snapshot(self): return frame,1
            result = self.run_align(bot,Camera())
            self.assertEqual(result['status'],'NO_LANES')
            self.assertEqual(bot.commands,[])
            self.assertFalse(self.last.exists())

    def test_already_aligned_saves_without_commands(self):
        bot = FakeBot()
        camera = FakeCamera(bot,target=dict(pan=80,tilt=5))
        result = self.run_align(bot,camera)
        self.assertEqual(result['status'],'ALIGNED')
        self.assertEqual(bot.commands,[])
        self.assertEqual(json.loads(self.last.read_text())['pan'],80)

    def test_signs_are_learned_from_images(self):
        for pan_sign,tilt_sign in ((10,10),(-10,10),(10,-10),(-10,-10)):
            with self.subTest(pan=pan_sign,tilt=tilt_sign):
                self.last.unlink(missing_ok=True)
                bot = FakeBot()
                target = dict(pan=83,tilt=8)
                result = self.run_align(bot,FakeCamera(bot,target=target,response=dict(pan=pan_sign,tilt=tilt_sign)))
                self.assertEqual(result['status'],'ALIGNED',result['reason'])
                self.assertEqual(np.sign(result['response_px_per_degree']['pan']),np.sign(pan_sign))
                self.assertEqual(np.sign(result['response_px_per_degree']['tilt']),np.sign(tilt_sign))
                self.assertLessEqual(abs(result['pan']-target['pan']),1)
                self.assertLessEqual(abs(result['tilt']-target['tilt']),1)
                prior = dict(pan=80,tilt=5)
                for servo,angle in bot.commands:
                    axis = 'pan' if servo == 1 else 'tilt'
                    self.assertEqual(abs(angle-prior[axis]),1)
                    prior[axis] = angle

    def test_five_simulated_initial_offsets(self):
        results = []
        for target in [dict(pan=85,tilt=10),dict(pan=75,tilt=0),dict(pan=85,tilt=0),dict(pan=75,tilt=10),dict(pan=83,tilt=8)]:
            self.last.unlink(missing_ok=True)
            bot = FakeBot()
            result = self.run_align(bot,FakeCamera(bot,target=target))
            self.assertEqual(result['status'],'ALIGNED',result['reason'])
            self.assertLessEqual(abs(result['pan']-target['pan']),1)
            self.assertLessEqual(abs(result['tilt']-target['tilt']),1)
            results.append(dict(target=target,pan=result['pan'],tilt=result['tilt'],moves=result['moves'],
                                simulated_wait_seconds=result['moves']*.3,status=result['status']))
        (align.OUTPUT/'simulated_offsets.json').write_text(json.dumps(dict(hardware=False,runs=results),indent=2)+'\n')

    def test_twenty_commands_max_and_old_last_preserved(self):
        self.seed()
        original = self.last.read_bytes()
        bot = FakeBot()
        class Camera:
            def snapshot(self):
                n = len(bot.commands)
                return shifted(30 if n%2 == 0 else -30),n+1
        result = self.run_align(bot,Camera())
        self.assertEqual(result['status'],'MAX_MOVES')
        self.assertEqual(len(bot.commands),20)
        self.assertEqual(self.last.read_bytes(),original)

    def test_pan_limit_blocks_command(self):
        self.seed(pan=90,response=dict(pan=-10,tilt=10))
        bot = FakeBot(pan=90)
        class Camera:
            def snapshot(self): return shifted(30),1
        result = self.run_align(bot,Camera())
        self.assertEqual(result['status'],'LIMIT')
        self.assertEqual(bot.commands,[])

    def test_tilt_limit_blocks_command(self):
        self.seed(tilt=0,response=dict(pan=10,tilt=-10))
        bot = FakeBot(tilt=0)
        class Camera:
            def snapshot(self):return shifted(dy=-30),1
        result = self.run_align(bot,Camera())
        self.assertEqual(result['status'],'LIMIT')
        self.assertEqual(bot.commands,[])

    def test_invalid_last_rejected_before_servo(self):
        for value in [91,69,True,'80']:
            self.last.write_text(json.dumps(dict(pan=value,tilt=5)))
            bot = FakeBot()
            with self.assertRaises(ValueError):
                align.restore_saved_pose(bot,self.last,sleep_fn=lambda seconds:None)
            self.assertEqual(bot.commands,[])

    def test_default_and_saved_pose_restore(self):
        for data,expected in [(None,[(1,80),(2,5)]),(dict(pan=82,tilt=6),[(1,82),(2,6)])]:
            if data is not None:self.last.write_text(json.dumps(data))
            bot = FakeBot()
            waits = []
            align.restore_saved_pose(bot,self.last,sleep_fn=waits.append)
            self.assertEqual(bot.commands,expected)
            self.assertEqual(waits,[.3,.3])

    def test_stale_frame_stops_after_probe(self):
        bot = FakeBot()
        class Camera:
            def snapshot(self): return shifted(30),1
        result = self.run_align(bot,Camera())
        self.assertEqual(result['status'],'STALE_FRAME')
        self.assertEqual(len(bot.commands),1)
        self.assertFalse(self.last.exists())

    def test_no_visible_response_stops_without_saving(self):
        bot = FakeBot()
        class Camera:
            sequence = 0
            def snapshot(self):
                self.sequence += 1
                return shifted(30),self.sequence
        result = self.run_align(bot,Camera())
        self.assertEqual(result['status'],'UNRELIABLE_RESPONSE')
        self.assertEqual(len(bot.commands),1)
        self.assertFalse(self.last.exists())

    def test_printed_i2c_error_is_failure(self):
        class Bot:
            def Ctrl_Servo(self,servo,angle):print('I2C error: simulated only')
        class Camera:
            def snapshot(self):return shifted(30),1
        with redirect_stdout(io.StringIO()):result = self.run_align(Bot(),Camera())
        self.assertEqual(result['status'],'ERROR')
        self.assertFalse(self.last.exists())

    def test_thirteen_existing_control_unchanged(self):
        old = subprocess.check_output(['git','show','5464ca0:missions/13_full_course.py'],cwd=ROOT,text=True)
        new = (ROOT/'missions/13_full_course.py').read_text()
        nodes = [{n.name:ast.dump(n) for n in ast.parse(source).body
                  if isinstance(n,(ast.FunctionDef,ast.ClassDef))} for source in (old,new)]
        for name,node in nodes[0].items():self.assertEqual(node,nodes[1][name],name)
        self.assertEqual(set(nodes[1])-set(nodes[0]),{'prepare_camera'})

    def test_thirteen_startup_only_restores_pose(self):
        self.assertFalse(align.LAST.exists(),'집 시험은 실제 last.json이 없는 상태에서 실행')
        spec = importlib.util.spec_from_file_location('full_course_startup_test',ROOT/'missions/13_full_course.py')
        course = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(course)
        bot = FakeBot()
        with mock.patch('time.sleep'):
            result = course.prepare_camera(bot)
        self.assertEqual(bot.commands,[(1,80),(2,5)])
        self.assertEqual(result['source'],'default')
        self.assertFalse(align.LAST.exists())

    def test_thirteen_cancel_does_not_import_driver(self):
        code = "import sys,runpy; sys.modules['Raspbot_Lib']=None; runpy.run_path('missions/13_full_course.py',run_name='__main__')"
        result = subprocess.run(['python3','-c',code],cwd=ROOT,input='n\n',capture_output=True,text=True,check=True)
        self.assertIn('중단했습니다',result.stdout)

    def test_photo_cli_with_driver_import_blocked(self):
        code = "import sys,runpy; sys.modules['Raspbot_Lib']=None; sys.argv=['14_camera_align.py','--photo','results/camera_align/reference_frame.png']; runpy.run_path('missions/14_camera_align.py',run_name='__main__')"
        result = subprocess.run(['python3','-c',code],cwd=ROOT,capture_output=True,text=True,check=True)
        data = json.loads(result.stdout)
        self.assertTrue(data['measurement']['reliable'])
        self.assertTrue(data['correction']['aligned'])


if __name__ == '__main__':
    photo_trial()
    unittest.main(verbosity=2)
