# 손으로 민 사진에서 "실제로 어느 쪽으로 돌았는지" 구하기 (윗부분 벽이 옆으로 밀린 양)
import cv2,numpy as np,glob,json,sys
src=sys.argv[1]
fs=sorted(glob.glob(src+"/*.jpg"))
g=[]
for f in fs:
    im=cv2.imread(f,0)
    g.append(None if im is None else cv2.resize(im[0:220],(320,110)).astype(np.float32))
win=cv2.createHanningWindow((320,110),cv2.CV_32F)
dx=[0.0]*len(g)
for i in range(1,len(g)-1):
    a,b=g[i-1],g[i+1]
    if a is None or b is None: continue
    (sx,sy),r=cv2.phaseCorrelate(a,b,win)
    dx[i]=float(sx)*2 if r>0.05 else 0.0   # 640폭 기준 픽셀, 0.2초 동안
d=np.array(dx); k=np.ones(5)/5; sm=np.convolve(d,k,mode="same")
turn=(-sm).tolist()          # +면 오른쪽으로 돈 것
json.dump(dict(files=[f.split("/")[-1] for f in fs],turn=turn),open(src.rstrip("/").split("/")[-1]+"_truth.json","w"))
for a in range(0,len(turn),20):
    seg=turn[a:a+20]; m=sum(seg)/len(seg)
    print(f"{a:04d} {m:+6.1f} "+("R"*min(30,int(m)) if m>0 else "L"*min(30,int(-m))))
