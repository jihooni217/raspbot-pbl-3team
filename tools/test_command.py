#!/usr/bin/env python3
# 지시서: specs/08-command.md
"""글 명령의 거부/대체/시간/거리/정지 규칙을 가짜 장치로 검증한다."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('command_test',ROOT/'missions/08_command.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Clock:
    def __init__(self):self.now = 0.
    def __call__(self):return self.now
    def sleep(self,seconds):self.now += max(0,seconds)


class Bot:
    def __init__(self,clock,distance=lambda now:50):
        self.clock,self.distance = clock,distance
        self.events = []
        self.wheels = [0]*4
        self.read_times = []
    def Ctrl_Muto(self,wheel,value):
        self.events.append(('wheel',self.clock(),wheel,value));self.wheels[wheel] = value
    def Ctrl_BEEP_Switch(self,value):self.events.append(('beep',self.clock(),value))
    def Ctrl_Ulatist_Switch(self,value):self.events.append(('ultra',self.clock(),value))
    def Ctrl_WQ2812_ALL(self,on,color):self.events.append(('light',self.clock(),on,color))
    def read_data_array(self,reg,count):
        if reg==0x1b:self.read_times.append(self.clock())
        mm = round(self.distance(self.clock())*10)
        return [mm>>8] if reg==0x1b else [mm&255]


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unit_',dir=ROOT/'results/command')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def executor(self,*,bot=None,confirm=lambda question:True,cancel=lambda:False,look=None):
        clock = bot.clock if bot is not None else Clock()
        bot = bot or Bot(clock)
        runner = m.HardwareExecutor(lambda:bot,confirm=confirm,cancel=cancel,
                                    clock=clock,sleep=clock.sleep,look=look)
        return runner,bot,clock

    def assert_stopped(self,bot):
        self.assertEqual(bot.wheels,[0]*4)
        tail = [event for event in bot.events if event[0]=='wheel'][-12:]
        self.assertEqual([(e[2],e[3]) for e in tail],[(i,0) for _ in range(3) for i in range(4)])

    def test_fixed_cases_keyword(self):
        for case in json.loads((ROOT/'results/command/cases.json').read_text()):
            answer = m.keyword_select(case['text'])
            self.assertEqual(answer['action'],case['action'],case['text'])
            if 'color' in case:self.assertEqual(answer['color'],case['color'])

    def test_all_actions_and_ranges(self):
        for action in m.ACTIONS:
            data = dict(action=action,say='시험')
            if action=='light':data['color']='red'
            self.assertEqual(m.validate(data)['action'],action)
        for action in m.MOTION:
            for bound in m.MOTION[action][2]:
                self.assertEqual(m.validate(dict(action=action,say='시험',seconds=bound))['seconds'],bound)
        for count in (1,2,3):self.assertEqual(m.validate(dict(action='beep',count=count,say='시험'))['count'],count)

    def test_malformed_ai_answers_are_rejected(self):
        bad = ['[]','[{"action":"stop","say":"x"}]','{"action":"jump","say":"x"}',
               '{"action":"forward","say":"x","speed":40}',
               '{"action":"stop","action":"forward","say":"x"}',
               '```json\n{"action":"stop","say":"x"}\n```',
               '{\n"action":"stop","say":"x"}',
               '{"action":"forward","seconds":NaN,"say":"x"}',
               '{"action":"forward","seconds":1e999,"say":"x"}',
               '{"action":"forward","seconds":'+str(10**400)+',"say":"x"}']
        bad.extend(json.dumps(dict(action=action,say='x',**extra)) for action,extra in [
            ('forward',dict(seconds=True)),('forward',dict(seconds='1')),('forward',dict(seconds=2.1)),
            ('backward',dict(seconds=1)),('slide_left',dict(seconds=.6)),('turn_left',dict(seconds=1.6)),
            ('beep',dict(count=True)),('beep',dict(count=0)),('beep',dict(count=4)),('beep',dict(count=1.5)),
            ('beep',dict(seconds=.4)),('light',dict(color='purple')),('stop',dict(seconds=1)),
            ('forward',dict(color='red')),('forward',dict(count=2))])
        for raw in bad:
            with self.subTest(raw=raw[:90]):
                with self.assertRaises(m.InvalidAnswer):m.parse_answer(raw)

    def test_all_ai_failures_fall_back_and_revalidate(self):
        for failure in ['not-json','{"action":"unsafe","say":"x"}',TimeoutError('timeout'),OSError('missing CLI'),
                        TypeError('가짜 전달 오류'),subprocess.TimeoutExpired('가짜 CLI',1)]:
            def ai(text,**kwargs):
                if isinstance(failure,Exception):raise failure
                return failure
            result = m.select_action('전진',ai=ai)
            self.assertTrue(result['fallback'])
            self.assertEqual(result['source'],'keyword')
            self.assertEqual(result['command']['action'],'forward')
            self.assertEqual(m.validate(result['command']),result['command'])

    def test_wrong_known_action_uses_keyword_fallback(self):
        result = m.select_action('전진',ai=lambda text,**kw:'{"action":"backward","say":"뒤로"}')
        self.assertTrue(result['fallback'])
        self.assertEqual(result['command']['action'],'forward')

    def test_request_constraints_survive_ai_omissions(self):
        examples = [
            ('속도40으로 앞으로',dict(action='forward',say='x')),
            ('속도200으로 끝까지 달려',dict(action='forward',say='x')),
            ('벽에 박아 버려',dict(action='forward',say='x')),
            ('창문 열어 줘',dict(action='forward',say='x')),
            ('앞으로5초',dict(action='forward',seconds=1,say='x')),
            ('앞으로 -1초',dict(action='forward',seconds=1,say='x')),
            ('후진1초',dict(action='backward',seconds=.5,say='x')),
            ('앞으로1m',dict(action='forward',say='x')),
            ('앞으로 가고 왼쪽으로 돌아',dict(action='forward',say='x')),
            ('앞으로 가고 앞으로 가',dict(action='forward',say='x')),
            ('부저4번',dict(action='beep',count=1,say='x')),
            ('부저0번',dict(action='beep',count=1,say='x')),
            ('부저1.5번',dict(action='beep',count=1,say='x')),
            ('보라색 불 켜 줘',dict(action='light',color='red',say='x'))]
        for text,data in examples:
            result = m.select_action(text,ai=lambda text,**kw:json.dumps(data))
            self.assertEqual(result['command']['action'],'refuse',text)
            self.assertEqual(m.keyword_select(text)['action'],'refuse',text)

    def test_unrequested_parameters_and_wrong_color_fall_back(self):
        for text,data,field,expected in [
            ('전진',dict(action='forward',seconds=1.5,say='x'),'seconds',1.),
            ('경적 울려 줘',dict(action='beep',count=3,say='x'),'count',1),
            ('빨간 불 켜 줘',dict(action='light',color='blue',say='x'),'color','red')]:
            result = m.select_action(text,ai=lambda text,**kw:json.dumps(data))
            self.assertTrue(result['fallback'])
            self.assertEqual(result['command'][field],expected)
        result = m.select_action('앞으로1.5초',ai=lambda text,**kw:'{"action":"forward","seconds":1.5,"say":"x"}')
        self.assertFalse(result['fallback'])
        self.assertEqual(result['command']['seconds'],1.5)

    def test_beep_count_and_light_off(self):
        self.assertEqual(m.keyword_select('경적 두 번 울려 줘')['count'],2)
        self.assertEqual(m.keyword_select('불 꺼 줘')['color'],'off')

    def test_version_discovery(self):
        paths = []
        for version in ('9.9.10','10.1.2'):
            path = self.folder/f'openai.chatgpt-{version}-linux-arm64/bin/linux-aarch64/codex'
            path.parent.mkdir(parents=True);path.write_text('test');path.chmod(0o755);paths.append(path)
        self.assertEqual(m.find_codex(self.folder),paths[-1])

    def stub(self,body):
        path = self.folder/'fake_codex'
        path.write_text('#!/usr/bin/python3\n'+body)
        path.chmod(0o755)
        return path

    def test_cli_argv_and_stdout_are_data_only(self):
        binary = self.stub('import sys\nprint("progress",file=sys.stderr)\nprint(\'{"action":"stop","say":"x"}\')\n')
        argv = m.codex_argv('x";touch nope',binary)
        self.assertEqual(argv[argv.index('-s')+1],'read-only')
        self.assertIn('model_reasoning_effort="low"',argv)
        self.assertIn('service_tier="default"',argv)
        self.assertIn('shell_tool',argv)
        self.assertEqual(m.parse_answer(m.ask_codex('전진',binary=binary))['action'],'stop')
        self.assertFalse((ROOT/'nope').exists())

    def test_cli_timeout_and_cancellation_reap_process(self):
        binary = self.stub('import time\ntime.sleep(5)\n')
        started = time.monotonic()
        with self.assertRaises(TimeoutError):m.ask_codex('전진',binary=binary,timeout=.05)
        self.assertLess(time.monotonic()-started,1)
        with self.assertRaises(m.Cancelled):m.ask_codex('전진',binary=binary,cancel=lambda:True)

    def test_dry_run_never_opens_hardware(self):
        class Executor:
            def perform(self,candidate):raise AssertionError('dry-run에 장치 실행')
        result = m.run_one('후진',dry_run=True,keywords_only=True,executor=Executor(),log_path=self.folder/'log.csv')
        self.assertEqual(result['plan']['speed'],30)
        self.assertEqual(result['plan']['seconds'],.5)
        self.assertEqual(result['result']['status'],'DRY_RUN')
        code = "import sys,runpy;sys.modules['Raspbot_Lib']=None;sys.modules['cv2']=None;sys.argv=['08_command.py','--dry-run','--keywords-only','--json','사진 찍어 줘'];runpy.run_path('missions/08_command.py',run_name='__main__')"
        completed = subprocess.run(['python3','-c',code],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(completed.stdout)['command']['action'],'look')

    def test_cancelled_selection_is_logged_without_device(self):
        def ai(text,**kwargs):raise m.Cancelled('q')
        path = self.folder/'cancel.csv'
        result = m.run_one('전진',dry_run=True,ai=ai,log_path=path)
        self.assertEqual(result['result']['status'],'CANCELLED')
        self.assertTrue(path.exists())
        self.assertEqual(len(path.read_text().splitlines()),2)

    def test_raw_ai_newlines_do_not_split_csv_record(self):
        path = self.folder/'lines.csv'
        result = m.run_one('전진',dry_run=True,ai=lambda text,**kw:'bad\njson',log_path=path)
        self.assertTrue(result['fallback'])
        self.assertEqual(len(path.read_text().splitlines()),2)

    def test_cleanup_sleep_failure_still_attempts_all_wheels(self):
        runner,bot,clock = self.executor()
        runner.bot = bot
        def fail_sleep(seconds):raise RuntimeError('가짜 sleep 오류')
        runner.sleep = fail_sleep
        self.assertTrue(runner._stop())
        self.assert_stopped(bot)

    def test_rear_space_asked_each_time_and_fixed_speed(self):
        questions = []
        runner,bot,clock = self.executor(confirm=lambda q:questions.append(q) or True)
        for _ in range(2):self.assertEqual(runner.perform(dict(action='backward',say='x'))['status'],'DONE')
        self.assertEqual(len(questions),3)
        self.assertIn('상자',questions[0]);self.assertTrue(all('뒤' in q for q in questions[1:]))
        self.assertEqual({abs(e[3]) for e in bot.events if e[0]=='wheel' and e[3]}, {30})
        self.assert_stopped(bot)

    def test_side_space_refusal_has_no_motion(self):
        answers = iter((True,False))
        runner,bot,clock = self.executor(confirm=lambda q:next(answers))
        self.assertEqual(runner.perform(dict(action='slide_left',say='x'))['status'],'REFUSED_SPACE')
        self.assertFalse(any(e[0]=='wheel' and e[3] for e in bot.events))
        self.assert_stopped(bot)

    def test_initial_readiness_refusal_has_no_motion(self):
        runner,bot,clock = self.executor(confirm=lambda q:False)
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'REFUSED_READY')
        self.assertFalse(any(e[0]=='wheel' and e[3] for e in bot.events))
        self.assert_stopped(bot)

    def test_preflight_25cm_and_in_motion_20cm(self):
        clock = Clock();bot = Bot(clock,lambda now:25)
        runner,bot,clock = self.executor(bot=bot)
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'REFUSED_OBSTACLE')
        self.assertFalse(any(e[0]=='wheel' and e[3] for e in bot.events))
        clock = Clock();bot = Bot(clock,lambda now:50 if now<1.13 else 20)
        runner,bot,clock = self.executor(bot=bot)
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'STOP_OBSTACLE')
        first_stop = next(e[1] for e in bot.events if e[0]=='wheel' and e[3]==0)
        self.assertLessEqual(first_stop,1.18)
        self.assertLessEqual(max(b-a for a,b in zip(bot.read_times,bot.read_times[1:])),.0500001)
        self.assert_stopped(bot)

    def test_fixed_half_second_and_wheel_signs(self):
        expected = dict(backward=[-30,-30,-30,-30],slide_left=[-30,30,30,-30],slide_right=[30,-30,-30,30])
        for action in ('backward','slide_left','slide_right'):
            runner,bot,clock = self.executor()
            result = runner.perform(dict(action=action,say='x'))
            self.assertAlmostEqual(result['elapsed'],.5)
            moving = [(e[2],e[3]) for e in bot.events if e[0]=='wheel' and e[3]][:4]
            self.assertEqual(moving,list(enumerate(expected[action])))
            self.assert_stopped(bot)

    def test_q_and_motor_failure_stop_all_four(self):
        runner,bot,clock = self.executor()
        runner.cancel = lambda:clock()>1.115
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'CANCELLED')
        self.assert_stopped(bot)
        clock = Clock()
        class FailingBot(Bot):
            def Ctrl_Muto(self,wheel,value):
                super().Ctrl_Muto(wheel,value)
                if wheel==2 and value:raise RuntimeError('가짜 모터 오류')
        runner,bot,clock = self.executor(bot=FailingBot(clock))
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'ERROR')
        self.assert_stopped(bot)

    def test_invalid_distance_and_printed_i2c_error_stop(self):
        clock = Clock()
        class BadSensor(Bot):
            def read_data_array(self,reg,count):return None
        runner,bot,clock = self.executor(bot=BadSensor(clock))
        self.assertEqual(runner.perform(dict(action='forward',say='x'))['status'],'ERROR')
        self.assert_stopped(bot)
        class PrintedError(Bot):
            def Ctrl_Muto(self,wheel,value):
                super().Ctrl_Muto(wheel,value)
                if value:print('I2C error: 가짜 시험')
        runner,bot,clock = self.executor(bot=PrintedError(Clock()))
        with redirect_stdout(io.StringIO()):result = runner.perform(dict(action='forward',say='x'))
        self.assertEqual(result['status'],'ERROR')
        self.assert_stopped(bot)

    def test_beep_light_distance_and_look_with_fake_devices(self):
        runner,bot,clock = self.executor(look=lambda:dict(status='DONE',seen=['person'],photo='가짜 사진'))
        self.assertEqual(runner.perform(dict(action='beep',count=3,say='x'))['count'],3)
        self.assertEqual(sum(e[0]=='beep' and e[2]==1 for e in bot.events),3)
        for color,index in m.COLORS.items():
            runner.perform(dict(action='light',color=color,say='x'))
            event = [e for e in bot.events if e[0]=='light'][-1]
            self.assertEqual(event[2:],(0,0) if index is None else (1,index))
        self.assertEqual(runner.perform(dict(action='distance',say='x'))['distance_cm'],50)
        self.assertEqual(runner.perform(dict(action='look',say='x'))['seen'],['person'])
        self.assertFalse(any(e[0]=='wheel' and e[3] for e in bot.events))
        self.assert_stopped(bot)


if __name__ == '__main__':
    unittest.main(verbosity=2)
