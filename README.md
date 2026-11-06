# 라즈봇 프로젝트 — 3조

대구대 「AI 자율주행 알고리즘 PBL」(2026.11.1~11.6) 3조 레포입니다.
Yahboom RASPBOT-V2 + Raspberry Pi 5가 **트랙 전체를 스스로 읽고 두 바퀴 돈 뒤 START에서 멈추도록** 만들었습니다.

조원: 조장 · 운전석 · 트랙·표지 · 측정 · 기록·발표 (이름 대신 역할)

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
| **13** | `missions/13_full_course.py` | **전체 코스 두 바퀴**: 갈림길 순서표 12칸, 파란 바닥 가속 45 · 빨간 바닥/「천천히」 감속 25 |
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
| 속도 구간 (가속·감속) | 0/5 | 5/5 |
| 글 명령 (바퀴 안 쓰는 시험) | — | 예문 10/10 · 거절 3/3 · 바꿔 말하기 5/5 |
| 실제 트랙 두 바퀴 | — | (11/5 학교 시험 뒤 채움) |

## 실행
- 전체 코스: `python3 missions/13_full_course.py` (먼저 `python3 missions/14_camera_align.py`로 카메라 맞추기)
- 글 명령: `python3 missions/08_command.py` (바퀴 없이 시험: `--dry-run`)
- 키보드 조종: `python3 tools/teleop.py`
- 조종판: `python3 missions/09_dashboard.py` → 같은 와이파이에서 `http://raspbot-03.local:8080`

## 안전 규칙
- 바퀴 속도 80 이하(데모 35/45/25), 바퀴 돌리기 전에 상자 위·바닥 확인
- 사람 얼굴이 나온 사진·영상, 비밀번호·API 키는 레포에 올리지 않는다
