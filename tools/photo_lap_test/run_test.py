# 07 판을 바퀴 없이 사진에 돌려, 실제로 돈 방향(정답)과 비교
import sys,glob,json,inspect,importlib.util,cv2,numpy as np
from pathlib import Path
SHIFT=200
def load(p):
    s=importlib.util.spec_from_file_location(Path(p).stem,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def t5(img):
    out=np.zeros_like(img); out[0:480-SHIFT]=img[SHIFT:]; return out
def run(mod_path, src, truth_file):
    m=load(mod_path); T=json.load(open(truth_file))
    fs=sorted(glob.glob(src+"/*.jpg")); four="last_name" in inspect.signature(m.find_lines).parameters
    c=m.LaneController(); rows=[]; stops=0
    for i,f in enumerate(fs):
        img=cv2.imread(f)
        if img is None: rows.append((i,T["turn"][i],None,"BAD")); continue
        fr=t5(img); t=i*0.1
        lines=m.find_lines(fr,c.previous,c.width,c.single_name) if four else m.find_lines(fr,c.previous,c.width)
        sp=c.update(lines,t); st=c.state
        if c.stopped:
            stops+=1; rows.append((i,T["turn"][i],None,st)); c=m.LaneController(); continue
        rows.append((i,T["turn"][i],sp[0]-sp[2],st))
    return rows,stops
def score(rows):
    turn=[r for r in rows if abs(r[1])>=15]; ok=sum(1 for r in turn if r[2] and r[2]*r[1]>0)
    bad=sum(1 for r in turn if r[2] and r[2]*r[1]<0); stop=sum(1 for r in turn if not r[2])
    straight=[r for r in rows if abs(r[1])<3 and r[2] is not None]; wob=sum(1 for r in straight if abs(r[2])>=30)
    return dict(turn_frames=len(turn),ok=ok,wrong=bad,no_steer=stop,straight=len(straight),wobble=wob)
if __name__=="__main__":
    src=sys.argv[1]; truth=sys.argv[2]
    for p in sys.argv[3:]:
        rows,stops=run(p,src,truth); s=score(rows)
        json.dump(rows,open(Path(p).stem+"_rows.json","w"))
        print(Path(p).stem, "멈춤",stops, s, flush=True)
