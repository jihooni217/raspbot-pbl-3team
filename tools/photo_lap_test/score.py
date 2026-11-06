# 사용: python3 ~/corner_test/score.py 판.py [판2.py ...]
#   → 바깥 모서리 5곳에서 오른쪽으로 바르게 꺾은 비율, 직선에서 크게 흔들린 수
import sys, json, os
START = os.getcwd()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
from run_test import run
P = json.load(open("problems.json"))
args = [os.path.abspath(os.path.join(START, a)) for a in sys.argv[1:]]
for p in args:
    rows, _ = run(p, "/home/pi/train_raw/lap_211306", "lap_211306_truth.json")
    print("==", os.path.basename(p))
    tot = okt = 0
    for name, a, b, d in P["모서리"]:
        seg = rows[a:b]
        ok = sum(1 for r in seg if r[2] and r[2] > 0)
        stop = sum(1 for r in seg if r[2] is None)
        tot += len(seg); okt += ok
        print(f"  {name:12s} 오른쪽으로 꺾음 {ok:3d}/{len(seg)}  멈춤 {stop}")
    wt = wn = 0
    for name, a, b in P["직선"]:
        seg = [r for r in rows[a:b] if r[2] is not None]
        wob = sum(1 for r in seg if abs(r[2]) >= 30)
        wt += wob; wn += len(seg)
        print(f"  {name:12s} 크게 흔들림 {wob:3d}/{len(seg)}")
    print(f"  => 모서리 맞힘 {100*okt//tot}%   직선 흔들림 {wt}/{wn}", flush=True)
