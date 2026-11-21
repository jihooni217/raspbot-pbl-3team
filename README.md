# 라즈봇 프로젝트 — 3조

대구대 「AI 자율주행 알고리즘 PBL」(2026.11.1~11.6) 3조 레포입니다.
Yahboom RASPBOT-V2 + Raspberry Pi 5가 **바깥 큰길 한 바퀴를 스스로 달리고, 바닥 색으로 속도를 바꾸고, 사람 모형·STOP 앞에서 멈췄다가 START 흰 선에서 정지하도록** 만들었습니다. 로터리와 천천히는 시험 단계이고 시연에는 넣지 않았습니다.

조원: 조장 · 운전석 · 트랙·표지 · 측정 · 기록·발표 (이름 대신 역할)

주행 영상: [큰길 한 바퀴 (33초, 소리 없음)](https://github.com/jihooni217/raspbot-pbl-3team/releases/download/demo-20261106/raspbot_outer_lap_20261105.mp4)

로터리 시험 영상: [로터리 단독 시험 (18초, 소리 없음, 마지막에 흰 바닥으로 이탈)](https://github.com/jihooni217/raspbot-pbl-3team/releases/download/demo-20261106/raspbot_rotary_test.mp4)

**바로 보기** (페이지에서 재생, 720p · 소리 없음)

큰길 한 바퀴

https://github.com/user-attachments/assets/10f29714-b9fe-476f-a1fe-a59d78784a65

로터리 단독 시험

https://github.com/user-attachments/assets/eed7b209-75b9-433f-b449-a0a8d11d4d99

## 일하는 방식
- 조가 `specs/`에 **지시서**(무엇을 · 왜 · 규칙표 · 숫자 성공 기준 · 안전)를 쓰고, Codex가 `missions/`에 코드를 만든다. Codex 수칙은 `AGENTS.md`.
- 실제로 어떻게 움직였는지는 `results/`와 `log.md`에, 주행 기록은 `results/runs.csv`에 남긴다.
- 고칠 때는 한 번에 하나만, 고친 뒤 **사진 시험**(`tools/photo_lap_test/`)으로 점수를 다시 잰다.

## 만든 것
| 번호 | 프로그램 | 하는 일 |
|---|---|---|
| 02 | `missions/02_line.py` | 라인센서로 종이 트랙 따라가기 |
| 03 | `missions/03_video.py` | 블랙박스 영상(시각·거리·상태 글자) |
| 04 | `missions/04_obstacle.py` | 장애물 25cm 앞 정지, 35cm 넘으면 재출발 |
| 05·06 | `missions/05_signs.py` · `06_drive_signs.py` | YOLO로 사람·STOP 찾기, 달리며 정지 |
| 07 | `missions/07_lap_1757.py` | 카메라로 노란 차선 따라가기 (기준 판) |
| **13** | `missions/13_full_course.py` | **`--outer-lap` 큰길 한 바퀴(발표 시연)**: 파란 바닥 기본 속도 80 · 빨간 바닥 25 · 그 외 35, 사람·STOP 정지, START 흰 선 정지. `--rotary-test`는 로터리 시험용(모델 미포함) |
| 14 | `missions/14_camera_align.py` | 출발 전 카메라 각도 자동 맞추기 (박스에서 꺼낸 뒤 틀어진 각도 보정) |
| 08 | `missions/08_command.py` | 한국어 글 명령 → AI가 정해진 동작 목록에서 하나만 고름, 목록 밖은 거절 |
| 09 | `missions/09_dashboard.py` | 브라우저 조종판 (자동주행 ON · 긴급 정지 · 실시간 로그) |

## before → after (사진 시험 · 측정)
| 항목 | before | after |
|---|---|---|
| 장애물 정지 거리 (12~18cm 안) | 1/1 실패 | 4/5 통과 |
| YOLO 표지 30장 | 18/30 (320 모델) | 26/30 (640 모델) |
| 카메라 차선 모서리 맞힘 | 28% | 81% |
| 전체 코스 경로 맞힘 | 60% | 87% |
| 속도 구간 (가속·감속, 사진 시험) | 0/5 | 5/5 |
| 글 명령 (바퀴 안 쓰는 시험) | — | 예문 10/10 · 거절 3/3 · 바꿔 말하기 5/5 |
| 글 명령 (11/6 상자 위 실물) | — | 예문 10/10 · 거절 3/3 · AI 판단 최대 9.46초 |
| 실제 트랙 큰길 한 바퀴 (11/6) | — | 7판 모두 FINISH, 37.3~43.8초 |
| 우리만의 기능: 바닥 색 속도 (11/6 실주행) | — | 7판 모두 파란 구간 약 5.5초 가속, 빨간 구간 평균 25 |
| 달리다가 정지 (11/6 실주행) | — | 사람 모형 5판, 왼쪽 STOP 4판. 오른쪽 자리 STOP은 인식 못함 |
| 로터리 시험 (11/5) | — | 7판 중 1판 한 바퀴. 안정화는 다음 과제 |

## 남은 한계
- 사람은 가까이서야 멈추고, 안 보이면 약 1.3초 뒤 재출발합니다. 지금 카메라 값에서 검은 바닥 판정이 맞지 않는 것이 원인입니다.
- 로터리는 도는 도중 가까운 다른 차선을 따라가 벗어나는 것으로 추정하며, 아직 확인하지 못했습니다.
- 천천히는 사진 인식까지 했고 주행에는 넣지 않았습니다.
- 옆 판을 파란 바닥으로 약 0.9초 잘못 본 판이 있고, 빛 반사에 약합니다.

## 실행
명령은 모두 로봇 안 `~/raspbot` 폴더에서 실행합니다(VS Code 터미널 또는 SSH). 바퀴가 도는 명령은 실행 전에 로봇 주변을 비웁니다. 주행 중에는 아무 키나 `Ctrl+C`로 멈춥니다.

### 혼자 할 때 순서
1. 확장보드 스위치를 켜고 1~2분 기다린다(로봇은 등록된 와이파이에 자동 연결).
2. 노트북을 로봇과 같은 와이파이에 연결한다.
3. VS Code 왼쪽 아래 `><` → `Connect to Host` → `pi@raspbot-03.local` (또는 IP) → 폴더 `/home/pi/raspbot` 열기.
4. VS Code 위 메뉴 `Terminal` → `New Terminal`에서 아래 명령을 실행한다.
5. 끝나면 `sudo poweroff` → 초록 불이 멈추면 스위치를 내린다.

`raspbot-03.local`로 안 될 때 IP 찾기: 공유기 관리 화면(iptime은 `http://192.168.0.1`)의 연결된 기기 목록에서 `raspbot-03`을 찾거나, Raspberry Pi Connect(`connect.raspberrypi.com`)로 들어가 `hostname -I`를 실행한다. IP는 켤 때마다 바뀔 수 있다.

### 아이폰 핫스팟으로 연결할 때
1. 아이폰 설정 → 개인용 핫스팟 → **다른 사람의 연결 허용** 켜기, **호환성 최대화** 켜기(꺼져 있으면 로봇이 핫스팟을 못 찾는다).
2. 핫스팟 설정 화면을 켜 둔 채로 둔다(화면을 벗어나면 잠시 뒤 신호를 숨긴다).
3. 로봇이 집 와이파이로 연결된 상태에서, 로봇 터미널에 새 핫스팟을 한 번 등록한다(이름·비밀번호는 직접 넣는다).
```bash
sudo nmcli dev wifi rescan
nmcli dev wifi list                                          # 핫스팟 이름이 보이는지 확인
sudo nmcli dev wifi connect "핫스팟이름" password "비밀번호"   # 이름에 띄어쓰기가 있으면 따옴표 필수
```
4. 로봇이 핫스팟으로 옮겨 가며 연결이 끊긴다. 노트북도 같은 핫스팟에 연결하고 다시 접속한다. 한 번 등록하면 다음부터는 자동으로 붙는다.

### 접속과 끄기
```bash
ssh pi@raspbot-03.local          # 이름이 안 잡히면 공유기에서 찾은 IP로 접속
cd ~/raspbot
sudo poweroff                    # 끄기. 초록 불이 멈춘 뒤 확장보드 스위치를 내림
```
노트북 cmd에서 바로 끄기: `ssh -t pi@raspbot-03.local sudo poweroff` (이름 대신 IP를 써도 됨)

### 검은 선 따라가기 (라인센서, 02)
```bash
python3 missions/02_line.py --check-sensors --seconds 3   # 바퀴 없이 센서만 읽기. 흰색 1, 검은색 0
python3 missions/02_line.py                               # 출발. 속도 50, 선을 1초 넘게 놓치면 정지
python3 tools/line_floor_trial.py --trial 1               # 같은 주행 + results/에 기록 (회차 1~5)
```
선 가운데에 올려 두면 센서는 `0 1 0 1`(가운데 두 칸 x1·x3이 검은색)이 나옵니다.

### 학교 트랙에서 달릴 때 (카메라, 13 — 발표 시연 코드)
1. 로봇을 START 흰 선 뒤, 바깥 큰길 차선 가운데에 놓는다. 트랙 위 사람·물건을 치운다.
2. 카메라 값을 맞춘다(전원을 켤 때마다 다시). 바퀴는 안 돈다.
3. 바퀴 없이 판단만 먼저 볼 수 있다(`--check`).
4. 출발. 한 바퀴 돌고 START 흰 선에서 스스로 멈춘다. 도중에 멈추려면 아무 키.
```bash
sh tools/camera_track_values.sh                                   # 1) 카메라 값 맞추기 (학교 트랙 조명 기준)
python3 missions/13_full_course.py --outer-lap --check            # 2) 바퀴 없이 판단만 보기
python3 missions/13_full_course.py --outer-lap                    # 3) 큰길 한 바퀴 출발
python3 missions/13_full_course.py --outer-lap --lights           #    상태 불빛까지 (발표 마지막 시연)
python3 missions/13_full_course.py --outer-lap --laps 2           #    두 바퀴
python3 missions/13_full_course.py --outer-lap --seconds 20       #    20초 뒤 자동 종료
```
- 속도: 파란 바닥 80 · 빨간 바닥 25 · 그 외 35. 사람·STOP 표지·앞 장애물(초음파 25cm)에서 멈춘다.
- 불빛: 멈춤 빨강 · 평소 초록 · 파란 바닥 가속 파랑 · 빨간 바닥 감속 노랑 깜빡임.
- 기록은 `results/full_course_날짜_시각.csv/.json`에 남는다.
- 조명이 달라 차선을 못 잡으면, 노트북에서 카메라 화면을 보며 값을 조절한다: `python tools/camera_tuner.py --host raspbot-03.local` (이름이 안 되면 IP)
- 로터리 시험(완성 안 됨, 흰 바닥으로 벗어날 수 있음): `python3 missions/13_full_course.py --rotary-test`

### 트랙용 다른 프로그램
```bash
python3 missions/07_lap_1757.py --check     # 노란 차선 따라가기 기준 판, 바퀴 없이 계산만
python3 missions/07_lap_1757.py             # 노란 차선 따라가기 (13번의 바탕)
python3 missions/14_camera_align.py         # 출발 전 카메라 각도 자동 맞추기 (바퀴 안 씀)
python3 missions/04_obstacle.py             # 장애물 25cm 앞 정지, 35cm 넘으면 재출발
python3 missions/06_drive_signs.py --trial 1   # 달리며 사람·STOP 보고 정지 (회차 이름)
```

### 그 밖
```bash
python3 missions/08_command.py            # 글 명령 (바퀴 없이 시험: --dry-run)
python3 tools/teleop.py                   # 키보드 조종
python3 missions/09_dashboard.py          # 조종판 → 같은 와이파이에서 http://raspbot-03.local:8080
```

## 안전 규칙
- 바퀴 속도 80 이하(데모 35/80/25), 바퀴 돌리기 전에 상자 위·바닥 확인
- 사람 얼굴이 나온 사진·영상, 비밀번호·API 키는 레포에 올리지 않는다
