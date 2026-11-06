# 전체 코스 점수: python3 ~/corner_test/score_route.py 판.py
#  방향 구간: 정답 쪽으로 꺾은 화면 비율 / S 구간: 크게(30 이상) 안 꺾은 비율 / fast·slow: 평균 속도
import sys, json, os, glob, inspect
START = os.getcwd(); HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); os.chdir(HERE)
import cv2
from run_test import load, t5
P = json.load(open("route.json")); BASE = P["기본속도"]
SRC = "/home/pi/train_raw/lap_211306"
def run(path):
    m = load(path); fs = sorted(glob.glob(SRC + "/*.jpg"))
    four = "last_name" in inspect.signature(m.find_lines).parameters
    c = m.LaneController(); rows = []
    for i, f in enumerate(fs):
        img = cv2.imread(f)
        if img is None: rows.append(None); continue
        fr = t5(img)
        lines = m.find_lines(fr, c.previous, c.width, c.single_name) if four else m.find_lines(fr, c.previous, c.width)
        sp = c.update(lines, i * 0.1)
        if c.stopped: rows.append(None); c = m.LaneController(); continue
        rows.append((sp[0] - sp[2], (sp[0] + sp[2]) / 2))
    return rows
for p in [os.path.abspath(os.path.join(START, a)) for a in sys.argv[1:]]:
    rows = run(p); print("==", os.path.basename(p)); good = tot = 0; spd_ok = spd_n = 0
    for name, a, b, d, spd in P["구간"]:
        seg = rows[a:b]; n = len(seg); stop = sum(1 for r in seg if r is None); live = [r for r in seg if r]
        msg = ""
        if d in "RL":
            s = 1 if d == "R" else -1; ok = sum(1 for r in live if r[0] * s > 0)
            msg = f"{'오른쪽' if d=='R' else '왼쪽'}으로 {ok:3d}/{n}"; good += ok; tot += n
        elif d == "S":
            ok = sum(1 for r in live if abs(r[0]) < 30); msg = f"곧게     {ok:3d}/{n}"; good += ok; tot += n
        if spd and live:
            v = sum(r[1] for r in live) / len(live); want = {"fast": v > BASE + 3, "slow": v < BASE - 3}[spd]
            spd_n += 1; spd_ok += want; msg += f"  평균속도 {v:4.1f} ({'가속' if spd=='fast' else '감속'} {'OK' if want else '안 됨'})"
        print(f"  {name:28s} {msg}  멈춤 {stop}")
    print(f"  => 경로 맞힘 {100*good//tot}%   속도 구간 {spd_ok}/{spd_n}", flush=True)
