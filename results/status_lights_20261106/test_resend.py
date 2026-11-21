import ast,importlib.util,json,time,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('blink_tests',Path(__file__).with_name('test_blink.py'));t=importlib.util.module_from_spec(s);s.loader.exec_module(t)
b=t.b;m=t.m
class ResendTests(unittest.TestCase):
 def test_same_value_resends_without_further_updates(self):
  bot=b.Bot();light=m.StatusLights(bot)
  try:
   light.update(t.GREEN);b.wait_for(lambda:len(bot.events)>=3,1.4)
   self.assertEqual([e[1:3] for e in bot.events[:3]],[(1,1)]*3)
   for i in (0,1):self.assertGreaterEqual(bot.events[i+1][3]-bot.events[i][3],.499)
  finally:light.close()
 def test_dropped_restart_color_recovers_by_refresh(self):
  class DroppedBot(b.Bot):
   visible=None;dropped=False
   def Ctrl_WQ2812_ALL(self,on,color):
    super().Ctrl_WQ2812_ALL(on,color)
    if on and color==1 and not self.dropped:self.dropped=True;return
    self.visible=(on,color)
  bot=DroppedBot();light=m.StatusLights(bot)
  try:
   light.update(t.STOP);b.wait_for(lambda:bot.visible==(1,0))
   light.update(t.GREEN);b.wait_for(lambda:bot.dropped)
   self.assertEqual(bot.visible,(1,0))
   b.wait_for(lambda:bot.visible==(1,1),.8)
  finally:light.close()
  self.assertEqual(bot.visible,(0,0))
 def test_frequent_same_reports_do_not_postpone_refresh(self):
  bot=b.Bot();light=m.StatusLights(bot);began=time.monotonic()
  try:
   while time.monotonic()-began<.65:
    light.update(t.GREEN);time.sleep(.005)
   self.assertGreaterEqual(len(bot.events),2)
   self.assertTrue(all(bot.events[i+1][3]-bot.events[i][3]>=.199 for i in range(len(bot.events)-1)))
  finally:light.close()
 def test_closing_off_phase_exits_without_resending(self):
  clock=[0.];bot=b.Bot();light=m.StatusLights(bot,clock=lambda:clock[0])
  light.update(t.RED);b.wait_for(lambda:len(bot.events)==1)
  clock[0]=.4;light.update(t.RED);b.wait_for(lambda:bot.events[-1][1:3]==(0,0))
  before=len(bot.events);light.close();time.sleep(.52)
  self.assertFalse(light.thread.is_alive());self.assertEqual(len(bot.events),before)
 def test_only_status_lights_changed(self):
  tree=ast.parse(Path(m.__file__).read_text())
  actual=[ast.dump(n) for n in tree.body if not isinstance(n,ast.ClassDef) or n.name!='StatusLights']
  self.assertEqual(actual,json.loads(Path('/tmp/status_lights_resend_before_ast.json').read_text()))
if __name__=='__main__':
 suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(b.Tests),unittest.defaultTestLoader.loadTestsFromTestCase(t.BlinkTests),unittest.defaultTestLoader.loadTestsFromTestCase(ResendTests)])
 r=unittest.TextTestRunner(verbosity=2).run(suite)
 raise SystemExit(0 if r.wasSuccessful() else 1)
