#!/usr/bin/env python3
# 지시서: specs/13-full-course.md
"""전체 코스 ①②: 07 차선 추적 + 색 바닥/천천히 구간 속도 계산.

장치 없는 사진 시험 단계다. 이 파일은 카메라와 바퀴를 열지 않는다.
find_lines(frame, previous, width) -> LaneController.update(lines, now).
갈림길 경로와 START 정지는 후속 단계에서 구현한다.
"""
import importlib.util
from pathlib import Path

import cv2
import numpy as np


_spec = importlib.util.spec_from_file_location(
    'full_course_lane_1757', Path(__file__).with_name('07_lap_1757.py'))
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)

COLOR_RATIO = 0.15
COLOR_HOLD_SECONDS = 0.5
COLOR_SPEEDS = {'blue': 45, 'red': 25}

# 트랙에 인쇄된 '천'의 위/아래 획 윤곽. 배경과 사진 좌표는 저장하지 않는다.
# 기울어진 글자를 정면으로 보는 경우도 포함하도록 세로 전단을 비교한다.
_SLOW_STROKES = (
    ((116,7),(93,6),(92,4),(95,1),(77,0),(72,3),(41,1),(36,3),
     (36,5),(59,7),(60,8),(57,10),(34,14),(0,15),(1,19),(30,19),
     (55,17),(70,25),(81,26),(92,23),(75,16),(75,12),(81,9),(111,11)),
    ((0,12),(4,14),(37,19),(115,28),(119,27),(125,22),(37,12),
     (37,9),(53,2),(42,0),(31,0)),
    # 반대 방향에서 원근으로 더 납작해진 같은 글자의 두 획.
    ((0,10),(0,13),(16,14),(19,8),(35,9),(36,10),(33,11),(34,13),
     (52,13),(57,14),(60,17),(76,17),(79,14),(102,15),(101,13),
     (80,13),(75,11),(76,9),(99,7),(93,5),(60,7),(37,3),(31,4),
     (35,5),(35,7),(19,6),(19,1),(17,0),(4,0)),
    ((0,0),(8,2),(54,3),(57,5),(57,7),(73,7),(69,2)),
)


def _stroke_mask(points, shear=0.0):
    points = np.asarray(points, dtype=float).reshape(-1, 2).copy()
    points -= points.min(axis=0)
    points /= np.maximum(points.max(axis=0), 1)
    points[:, 1] += shear * points[:, 0]
    points -= points.min(axis=0)
    points /= np.maximum(points.max(axis=0), 1)
    mask = np.zeros((32, 64), np.uint8)
    cv2.fillPoly(mask, [np.rint(points * (63, 31)).astype(np.int32)], 1)
    return mask.astype(bool)


_STROKE_MASKS = tuple(tuple(variant for points in _SLOW_STROKES[kind::2]
                            for shear in (-.5, -.25, 0, .25, .5)
                            for variant in (_stroke_mask(points, shear),
                                            _stroke_mask(points, shear)[::-1, ::-1]))
                      for kind in (0, 1))


def find_floor_color(frame):
    # 사진 시험의 아래쪽 검은 여백을 빼고 실제 화면의 가까운 바닥을 본다.
    occupied_rows = np.flatnonzero(np.any(frame != 0, axis=(1, 2)))
    bottom = int(occupied_rows[-1]) + 1 if occupied_rows.size else frame.shape[0]
    top = bottom * 3 // 4
    width = frame.shape[1]
    hsv = cv2.cvtColor(frame[top:bottom, width // 5:width * 4 // 5],
                       cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 90, 60), (130, 255, 255))
    red = (cv2.inRange(hsv, (0, 90, 60), (10, 255, 255)) |
           cv2.inRange(hsv, (170, 90, 60), (179, 255, 255)))
    blue_ratio = float(np.count_nonzero(blue) / blue.size)
    red_ratio = float(np.count_nonzero(red) / red.size)
    color = ('red' if red_ratio > COLOR_RATIO else
             'blue' if blue_ratio > COLOR_RATIO else None)
    return dict(color=color, blue_ratio=blue_ratio, red_ratio=red_ratio,
                roi=(width // 5, top, width * 4 // 5, bottom))


def find_lines(frame, previous=None, width=None):
    lines = lane.find_lines(frame, previous, width)
    lines['floor'] = find_floor_color(frame)
    lines['slow'] = find_slow_markers(frame)
    return lines


def find_slow_markers(frame):
    """흰 글자와 구불길 끝 표식 인식. slow 모델로 바꿀 때 이 함수만 교체.

    반환: text / roundabout_near / crossing_near(bool), 확인용 boxes.
    프레임 번호·시각·경로 정답을 받지 않는 장치 없는 인식 함수다.
    """
    occupied = np.flatnonzero(np.any(frame != 0, axis=(1, 2)))
    bottom = int(occupied[-1]) + 1 if occupied.size else frame.shape[0]
    width = frame.shape[1]
    hsv = cv2.cvtColor(frame[:bottom], cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 150), (179, 65, 255))
    white[:int(bottom * .4)] = 0
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    glyphs, bars, stroke_types, stroke_scores = [], [], [], []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        hull = cv2.contourArea(cv2.convexHull(contour))
        solidity = area / hull if hull else 1.0
        if (area >= 40 * width / 640 and w >= width * .018 and
                h >= bottom * .018 and 1.6 < w / h < 14 and .2 < solidity < .75):
            shape = _stroke_mask(contour)
            scores = [max(np.count_nonzero(shape & ref) / np.count_nonzero(shape | ref)
                          for ref in variants) for variants in _STROKE_MASKS]
            if max(scores) >= .55:
                glyphs.append((x, y, w, h))
                stroke_types.append(int(np.argmax(scores)))
                stroke_scores.append(max(scores))
        if (area >= 80 * width / 640 and solidity >= .85 and
                w >= width * .02 and h >= bottom * .025 and
                y + h / 2 > bottom * .85):
            bars.append((x, y, w, h))
    pairs = []
    for i, (x, y, w, h) in enumerate(glyphs):
        for j in range(i + 1, len(glyphs)):
            xx, yy, ww, hh = glyphs[j]
            overlap = min(x + w, xx + ww) - max(x, xx)
            separation = abs(y + h / 2 - yy - hh / 2)
            if (stroke_types[i] != stroke_types[j] and overlap > min(w, ww) * .5 and
                    min(h, hh) * .25 < separation < max(h, hh) * 2 and
                    min(stroke_scores[i], stroke_scores[j]) >= .6 and
                    stroke_scores[i] + stroke_scores[j] >= 1.4):
                pairs.append(((x + w / 2 + xx + ww / 2) / 2,
                              (y + h / 2 + yy + hh / 2) / 2))
    text = bool(pairs)
    crossing = (len(bars) >= 3 and
                max(x + w for x, y, w, h in bars) - min(x for x, y, w, h in bars)
                > width * .35)

    # 흰 타원 윤곽과 내부 녹색을 함께 보아 화살표/글자와 구분한다.
    bright = cv2.inRange(hsv, (0, 0, 180), (179, 65, 255))
    contours, _ = cv2.findContours(bright, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    roundabouts = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (len(contour) >= 5 and w >= width * .125 and h >= bottom * .07
                and 3 < w / h < 20 and y + h / 2 > bottom * .45):
            continue
        green = cv2.inRange(hsv[y:y+h, x:x+w], (30, 35, 70), (90, 255, 255))
        if np.count_nonzero(green) / green.size < .1:
            continue
        (cx, cy), (a, b), angle = cv2.fitEllipse(contour)
        if min(a, b) <= 0:
            continue
        points = contour[:, 0, :].astype(float) - (cx, cy)
        theta = np.deg2rad(angle)
        u = points[:, 0] * np.cos(theta) + points[:, 1] * np.sin(theta)
        v = -points[:, 0] * np.sin(theta) + points[:, 1] * np.cos(theta)
        error = np.mean(np.abs(np.sqrt((u / (a / 2)) ** 2 + (v / (b / 2)) ** 2) - 1))
        if error < .18:
            roundabouts.append((x, y, w, h))
    return dict(text=bool(text), roundabout_near=bool(roundabouts),
                crossing_near=bool(crossing),
                boxes=dict(glyphs=glyphs, bars=bars, roundabouts=roundabouts))


class LaneController(lane.LaneController):
    """07의 선 추적과 정지를 쓰고 TRACK 중 기본 속도만 바꾼다."""

    def __init__(self):
        super().__init__()
        self.floor_color = None
        self.color_missing_since = None
        self.base_speed = lane.BASE_SPEED
        self.slow_active = False
        self.slow_seen_since = None
        self.slow_end_since = None

    def update(self, lines, now):
        speeds = super().update(lines, now)
        seen = lines.get('floor', {}).get('color')
        if seen in COLOR_SPEEDS:
            self.floor_color = seen
            self.color_missing_since = None
        elif self.floor_color is not None:
            if self.color_missing_since is None:
                self.color_missing_since = now
            if now - self.color_missing_since >= COLOR_HOLD_SECONDS:
                self.floor_color = None
                self.color_missing_since = None
        self.base_speed = COLOR_SPEEDS.get(self.floor_color, lane.BASE_SPEED)
        slow = lines.get('slow', {})
        if slow.get('text'):
            if self.slow_seen_since is None:
                self.slow_seen_since = now
            if now - self.slow_seen_since >= .2 - 1e-9:
                self.slow_active = True
            self.slow_end_since = None
        else:
            self.slow_seen_since = None
            if slow.get('roundabout_near') or slow.get('crossing_near'):
                if self.slow_end_since is None:
                    self.slow_end_since = now
                if now - self.slow_end_since >= .5 - 1e-9:
                    self.slow_active = False
            else:
                self.slow_end_since = None
        if self.slow_active:
            self.base_speed = 25
        if self.state in ('TRACKBOTH', 'TRACKLEFT', 'TRACKRIGHT') and not self.stopped:
            offset = self.base_speed - lane.BASE_SPEED
            self.speeds = tuple(max(0, min(lane.MAX_SPEED, v + offset)) for v in speeds)
        return self.speeds

    def report(self):
        return dict(super().report(), floor_color=self.floor_color,
                    base_speed=self.base_speed, slow_active=self.slow_active)


if __name__ == '__main__':
    print('①② 사진 시험용입니다. 바퀴는 움직이지 않습니다.')
    print('python3 ~/corner_test/score_route.py missions/13_full_course.py')
    print('python3 ~/corner_test/score.py missions/13_full_course.py')
