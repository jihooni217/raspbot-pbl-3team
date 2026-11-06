#!/bin/sh
# 트랙 주행용 카메라 값. 13번 --outer-lap 3판 연속 완주(2026-11-05 저녁, 학교 트랙)에 쓴 값이다.
# 전원을 껐다 켜면 값이 바뀔 수 있으니 달리기 전에 실행한다. 조명이 다르면 tools/camera_tuner.py로 다시 본다.
# 바퀴는 돌리지 않는다.
set -e
for value in auto_exposure=1 exposure_time_absolute=10 \
             white_balance_automatic=0 white_balance_temperature=3800 \
             backlight_compensation=128 brightness=-50 contrast=30 \
             saturation=80 hue=250 gamma=93 sharpness=1; do
    v4l2-ctl -d /dev/video0 -c "$value"
done
v4l2-ctl -d /dev/video0 -C exposure_time_absolute,white_balance_temperature,saturation,hue
