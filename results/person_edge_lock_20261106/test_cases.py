import csv, importlib.util, json, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path('/home/pi/raspbot')
s=importlib.util.spec_from_file_location('edge_safety',ROOT/'missions/13_full_course.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
OUT=ROOT/'results/person_edge_lock_20261106'
class Cases(unittest.TestCase):
    def packet(self,c,box,t,inside=True):
        found=[] if box is None else [('person',.9,box)]
        point=dict(near=True,inside=inside,basis='two_lines',foot=[320,250],bounds=[100,540],offroad_reason=None)
        with patch.object(m,'foot_on_lane',return_value=point):
            c.step(dict(sequence=t,captured_at=t,found=found,context=dict(width=640,height=280,frame_height=480)),t)
        return c.state
    def stopped(self,box):
        c=m.SafetyController(require_distance=False)
        self.packet(c,box,0);self.packet(c,box,.1)
        self.assertEqual(c.state,'PERSONWAIT')
        return c
    def test_actual_record_boxes(self):
        rows=list(csv.DictReader((ROOT/'results/full_course_20261106_152449_132755.csv').open()))
        start=float(rows[0]['wall_seconds']);c=m.SafetyController(require_distance=False)
        last=None;trace=[]
        for r in rows:
            t=float(r['wall_seconds'])-start
            if not 5.6<=t<=8.5:continue
            people=json.loads(r['person_score_feet_inside'] or '[]')
            key=r['person_score_feet_inside']
            if key==last and not (not people):continue
            last=key
            points={tuple(p['box']):{k:v for k,v in p.items() if k not in ('box','score')} for p in people}
            with patch.object(m,'foot_on_lane',side_effect=lambda box,*a,**kw:points[tuple(box)]):
                c.step(dict(sequence=t,captured_at=t,found=[('person',p['score'],p['box']) for p in people],
                            context=dict(width=640,height=280,frame_height=480)),t)
            trace.append(dict(t=t,state=c.state,boxes=[p['box'] for p in people]))
            if t>=6.283:self.assertEqual(c.state,'PERSON_CHECK15')
        self.assertTrue(c.person_locked)
        (OUT/'record_replay.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
    def test_far_person_resumes_after_one_second(self):
        c=self.stopped((280,100,50,100))
        self.assertEqual(self.packet(c,None,.2),'PERSONWAIT')
        self.assertEqual(self.packet(c,None,1.19),'PERSONWAIT')
        self.assertEqual(self.packet(c,None,1.21),'CLEAR')
    def test_outside_person_never_stopped(self):
        c=m.SafetyController(require_distance=False)
        for t in (0,.1,.2):self.assertEqual(self.packet(c,(517,1,121,425),t,False),'CLEAR')
        self.assertEqual(self.packet(c,None,.3),'CLEAR');self.assertFalse(c.person_locked)
    def test_height_uses_full_480_not_effective_280(self):
        for h,want in ((239,'CLEAR'),(240,'PERSON_CHECK15')):
            c=self.stopped((250,0,60,h))
            self.packet(c,None,.2);self.assertEqual(self.packet(c,None,1.21),want)
    def test_left_and_right_edge_thresholds(self):
        for x,w,want in ((5,50,'PERSON_CHECK15'),(6,50,'CLEAR'),(580,55,'PERSON_CHECK15'),(580,54,'CLEAR')):
            c=self.stopped((x,100,w,100))
            self.packet(c,None,.2);self.assertEqual(self.packet(c,None,1.21),want)
    def test_last_box_replaces_old_close_box(self):
        c=self.stopped((517,1,121,425))
        self.packet(c,(280,100,50,100),.2);self.packet(c,None,.3)
        self.assertEqual(self.packet(c,None,1.31),'CLEAR')
    def test_stale_packet_is_not_disappearance(self):
        c=self.stopped((517,1,121,425))
        c.step(dict(sequence=2,captured_at=.1,found=[],context={}),1.)
        self.assertEqual(c.state,'STALEVISION');self.assertFalse(c.person_locked)
    def test_stop_remains_three_seconds(self):
        c=m.SafetyController(require_distance=False)
        for t in (0,.1):
            c.step(dict(sequence=t,captured_at=t,found=[('stop sign',.9,(200,100,60,60))],context=dict(width=640,height=280)),t)
            c.motor_sent(m.lane.STOP,t)
        self.assertEqual(c.state,'STOPWAIT')
        self.assertAlmostEqual(c.signs.stop_until,3.1)
        for t in (1.,2.,3.099,3.101):
            c.step(dict(sequence=t,captured_at=t,found=[],context=dict(width=640,height=280)),t)
            self.assertEqual(c.state,'STOPWAIT' if t<3.1 else 'CLEAR')
    def test_start_finish_rule_unchanged(self):
        c=m.LaneController();c.route_step=12;c.start_passes=1
        lines=dict(start=dict(visible=True,near=True),slow={},traces=[])
        c._route(lines,0);self.assertFalse(c.stopped)
        c._route(lines,.21);self.assertTrue(c.stopped)
        self.assertEqual(c.state,'FINISH');self.assertEqual(c.start_passes,2)
if __name__=='__main__':unittest.main(verbosity=2)
