import importlib.util,io,json,sys,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager,redirect_stdout
ROOT=Path('/home/pi/raspbot')
s=importlib.util.spec_from_file_location('lights_course',ROOT/'missions/13_full_course.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def wait_for(fn,seconds=1):
 end=time.monotonic()+seconds
 while not fn():
  if time.monotonic()>end:raise AssertionError('fake light response timeout')
  time.sleep(.002)
class Bot:
 def __init__(self):self.events=[]
 def Ctrl_Muto(self,n,v):self.events.append(('motor',n,v,time.monotonic()))
 def Ctrl_WQ2812_ALL(self,on,c):self.events.append(('light',on,c,time.monotonic()))
 def Ctrl_Ulatist_Switch(self,on):pass
class Resource:
 inference_count=0;paths={}
 def __init__(self,*a):pass
 def start(self):return self
 def close(self):pass
class Tests(unittest.TestCase):
 def test_priority_and_colors(self):
  color=m.StatusLights.color
  for speeds,floor,base,want in [((0,0,0,0),'blue',80,0),((35,35,35,35),None,35,1),((80,80,80,80),'blue',80,2),((25,25,25,25),'red',25,3),((25,25,25,25),'blue',25,1)]:
   self.assertEqual(color(dict(speeds=speeds,floor_color=floor,base_speed=base)),want)
 def test_change_only_and_rate_and_off(self):
  b=Bot();l=m.StatusLights(b)
  try:
   report=dict(speeds=(35,)*4)
   l.update(report);wait_for(lambda:len(b.events)==1)
   for _ in range(50):l.update(report)
   time.sleep(.22);self.assertEqual(len(b.events),1)
   l.update(dict(speeds=(0,)*4));wait_for(lambda:len(b.events)==2)
   l.update(dict(speeds=(80,)*4,floor_color='blue',base_speed=80))
   wait_for(lambda:len(b.events)==3)
  finally:l.close()
  self.assertEqual([(e[1],e[2]) for e in b.events],[(1,1),(1,0),(1,2),(0,0)])
  self.assertTrue(all(b.events[i+1][3]-b.events[i][3]>=.199 for i in range(len(b.events)-1)))
 def test_latest_color_coalesces(self):
  b=Bot();l=m.StatusLights(b)
  try:
   l.update(dict(speeds=(0,)*4));wait_for(lambda:len(b.events)==1)
   l.update(dict(speeds=(35,)*4));l.update(dict(speeds=(25,)*4,floor_color='red',base_speed=25))
   wait_for(lambda:len(b.events)==2)
   self.assertEqual(b.events[1][2],3)
  finally:l.close()
 def test_slow_error_does_not_block_motor_stop(self):
  entered=threading.Event();release=threading.Event();b=Bot()
  def broken(on,c):
   entered.set();release.wait(1);raise OSError('fake LED failure')
  b.Ctrl_WQ2812_ALL=broken;l=m.StatusLights(b)
  try:
   l.update(dict(speeds=(35,)*4));self.assertTrue(entered.wait(1))
   began=time.monotonic()
   l.update(dict(speeds=(0,)*4))
   motor=m.MotorOutput(b,sleep_fn=lambda _:None);motor.close()
   self.assertLess(time.monotonic()-began,.05)
   self.assertEqual(len(b.events),12)
   release.set();wait_for(lambda:bool(l.errors))
  finally:release.set();l.close()
 def test_light_print_cannot_trigger_motor_i2c_error(self):
  entered=threading.Event();emit=threading.Event();printed=threading.Event();b=Bot()
  def noisy(on,c):
   if on:
    entered.set();emit.wait(1);print('Ctrl_WQ2812 I2C error');printed.set()
  b.Ctrl_WQ2812_ALL=noisy;l=m.StatusLights(b)
  try:
   l.update(dict(speeds=(35,)*4));self.assertTrue(entered.wait(1))
   def good_motor():emit.set();self.assertTrue(printed.wait(1))
   m.checked_driver_call(good_motor)
   def bad_motor():print('motor I2C error')
   with self.assertRaisesRegex(RuntimeError,'I2C error'):m.checked_driver_call(bad_motor)
  finally:emit.set();l.close()
 def fake_main(self,lights,mode='done',check=False):
  b=Bot()
  @contextmanager
  def keyboard():yield lambda:mode=='q'
  def run(camera,vision,distance,keys,stream,motor,**kw):
   try:
    for speeds,floor,base in [((35,)*4,None,35),((25,)*4,'red',25)]:
     motor(speeds)
     report=dict(speeds=speeds,floor_color=floor,base_speed=base,runtime_lane_frames=1,state='TRACKBOTH')
     kw['on_report'](report)
    if mode=='ctrlc':raise KeyboardInterrupt
    if mode=='error':raise RuntimeError('fake drive error')
    if mode=='q':keys()
    return dict(state='FINISH')
   finally:kw['on_stop']()
  with tempfile.TemporaryDirectory(prefix='lights_main_') as d:
   with patch.dict(sys.modules,{'Raspbot_Lib':types.SimpleNamespace(Raspbot=lambda:b)}),patch('builtins.input',return_value='y'),patch.object(m,'__file__',str(Path(d)/'missions/13_full_course.py')),patch.object(m,'prepare_camera',return_value=dict(pan=80,tilt=5,source='fake')),patch.object(m.lane.video,'LatestCamera',Resource),patch.object(m,'FullCourseVisionWorker',Resource),patch.object(m,'FullCourseRecorder',Resource),patch.object(m.obstacles,'keyboard_stop',keyboard),patch.object(m,'run_safety_loop',side_effect=run),patch.object(m.time,'sleep',lambda _:None),redirect_stdout(io.StringIO()):
    args=(['--lights'] if lights else [])+(['--check'] if check else [])
    code=m.main(args)
   result=json.loads(next((Path(d)/'results').glob('*.json')).read_text())
  return b.events,code,result
 def test_main_all_exit_paths_off_and_motor_first(self):
  for mode in ('done','error','q','ctrlc'):
   with self.subTest(mode=mode):
    events,code,r=self.fake_main(True,mode)
    lamps=[(i,e) for i,e in enumerate(events) if e[0]=='light']
    self.assertTrue(lamps);self.assertGreaterEqual(lamps[0][0],4)
    self.assertEqual(lamps[-1][1][1:3],(0,0))
    self.assertTrue(all(e[2]==0 for e in [e for e in events if e[0]=='motor'][-12:]))
    self.assertEqual(code,1 if mode=='error' else 0)
 def test_optout_zero_light_calls_and_same_motor_values(self):
  off,_,r=self.fake_main(False);on,_,_=self.fake_main(True)
  self.assertFalse(any(e[0]=='light' for e in off));self.assertNotIn('lights_errors',r)
  self.assertEqual([e[:3] for e in off if e[0]=='motor'],[e[:3] for e in on if e[0]=='motor'])
 def test_check_never_sends_motor(self):
  events,code,r=self.fake_main(True,check=True)
  self.assertFalse(any(e[0]=='motor' for e in events));self.assertEqual(code,0)
  self.assertEqual([e for e in events if e[0]=='light'][-1][1:3],(0,0))
if __name__=='__main__':unittest.main(verbosity=2)
