import importlib.util,time,unittest,ast
from pathlib import Path
s=importlib.util.spec_from_file_location('base_lights_tests',Path(__file__).with_name('test_lights.py'))
b=importlib.util.module_from_spec(s);s.loader.exec_module(b);m=b.m
RED=dict(speeds=(25,)*4,floor_color='red',base_speed=25)
GREEN=dict(speeds=(35,)*4)
STOP=dict(speeds=(0,)*4,floor_color='red',base_speed=25)
BLUE=dict(speeds=(80,)*4,floor_color='blue',base_speed=80)
class BlinkTests(unittest.TestCase):
 def test_boundaries_no_wait_and_restart(self):
  now=[10.];light=m.StatusLights(b.Bot(),clock=lambda:now[0])
  try:
   for t,want in [(10,3),(10.399,3),(10.4,None),(10.799,None),(10.8,3),(11.2,None),(11.6,3)]:
    now[0]=t;light.update(RED);self.assertEqual(light.desired,want)
   now[0]=11.7;light.update(GREEN);self.assertEqual(light.desired,1);self.assertIsNone(light.yellow_since)
   now[0]=11.71;light.update(RED);self.assertEqual(light.desired,3)
  finally:light.close()
 def test_stop_overrides_off_phase_and_steady_colors(self):
  now=[0.];light=m.StatusLights(b.Bot(),clock=lambda:now[0])
  try:
   light.update(RED);now[0]=.5;light.update(RED);self.assertIsNone(light.desired)
   light.update(STOP);self.assertEqual(light.desired,0);self.assertIsNone(light.yellow_since)
   for report,want in [(STOP,0),(GREEN,1),(BLUE,2)]:
    for t in (1.,1.5,2.,2.5):
     now[0]=t;light.update(report);self.assertEqual(light.desired,want)
  finally:light.close()
 def test_real_output_cycle_and_stop_rate(self):
  bot=b.Bot();light=m.StatusLights(bot);start=time.monotonic()
  try:
   while time.monotonic()-start<.86:
    light.update(RED);time.sleep(.005)
   b.wait_for(lambda:len(bot.events)>=3)
   self.assertEqual([(e[1],e[2]) for e in bot.events[:3]],[(1,3),(0,0),(1,3)])
   for i in (0,1):self.assertGreaterEqual(bot.events[i+1][3]-bot.events[i][3],.38)
   light.update(STOP);b.wait_for(lambda:bot.events[-1][1:3]==(1,0))
  finally:light.close()
  self.assertTrue(all(bot.events[i+1][3]-bot.events[i][3]>=.199 for i in range(len(bot.events)-1)))
 def test_no_blink_wait_calls_in_update(self):
  tree=ast.parse(Path(m.__file__).read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StatusLights')
  update=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='update')
  self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('sleep','wait','join') for n in ast.walk(update)))
if __name__=='__main__':
 suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(b.Tests),unittest.defaultTestLoader.loadTestsFromTestCase(BlinkTests)])
 r=unittest.TextTestRunner(verbosity=2).run(suite)
 raise SystemExit(0 if r.wasSuccessful() else 1)
