#!/usr/bin/env python3
# 지시서: specs/13-full-course.md
"""전체 코스 ①②③④: 07 차선 추적 + 경로/속도 + 사람·STOP·초음파 정지.

사진 시험 import는 장치를 쓰지 않는다. 직접 실행은 START/바닥 확인 후 실제 주행,
--check는 같은 센서/영상/판단 흐름을 사용하며 바퀴 명령을 전혀 보내지 않는다.
find_lines(frame, previous, width) -> LaneController.update(lines, now).
③은 표식 순서1~12와 갈림길 선택을 계산한다. --seconds로 시험 시간을 제한한다.
"""
import importlib.util
import argparse
from collections import deque
from contextlib import redirect_stdout
import csv
from datetime import datetime
import json
import io
import math
from pathlib import Path
import threading
import time

import cv2
import numpy as np


_spec = importlib.util.spec_from_file_location(
    'full_course_lane_1757', Path(__file__).with_name('07_lap_1757.py'))
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)

COLOR_RATIO = 0.15
COLOR_HOLD_SECONDS = 0.5
COLOR_SPEEDS = {'blue': 45, 'red': 25}
MARKER_VISIBLE_HEIGHT = 280
MIN_NORMAL_WIDTH_RATIO = .65
CORNER_ASPECT_RATIO = 3.
CORNER_HOLD_SECONDS = 1.3
CORNER_LIMIT_SECONDS = CORNER_HOLD_SECONDS  # 기존 영상 분석 도구의 상한 표시 호환
CORNER_COOLDOWN_SECONDS = 4.
CORNER_WHITE_RATIO = .6
CORNER_REACQUIRE_SECONDS = .5
WHITE_DEPARTURE_SECONDS = .5
NORMAL_WIDTH_SAMPLES = 15
CORNER_DIRECTIONS = {step:'RIGHT' for step in (1,2,5,8,9,10,11,12)}


def marker_frame(frame):
    """표시/안전 인식용 복사본. 좌표를 옮기지 않고 사진 시험의 여백만 맞춘다."""
    result = frame.copy()
    result[MARKER_VISIBLE_HEIGHT:] = 0
    return result


def corner_white_floor(frame):
    """⑤만 쓰는 실제 앞바닥. 흰 인쇄 일부와 화면 대부분의 흰 섬을 구분."""
    occupied = np.flatnonzero(np.any(frame!=0,axis=(1,2)))
    bottom = int(occupied[-1])+1 if occupied.size else len(frame)
    width = frame.shape[1]
    hsv = cv2.cvtColor(frame[bottom*3//4:bottom,width//5:width*4//5],cv2.COLOR_BGR2HSV)
    return float(np.mean((hsv[:,:,1]<=65)&(hsv[:,:,2]>=180)))

# 장치를 열지 않는 모듈/판단기만 재사용한다. 06/04/07의 파일과 전역 설정은 바꾸지 않는다.
reactions = lane.load('full_course_reactions', '06_drive_signs.py')
obstacles = lane.load('full_course_obstacles', '04_obstacle.py')

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
    markers = marker_frame(frame)
    lines['floor'] = find_floor_color(markers)
    lines['slow'] = find_slow_markers(markers)
    lines['start'] = find_start_markers(markers)
    lines['dividers'] = find_lane_dividers(markers)
    # 07의 검출 범위와 노란색 기준을 그대로 써 선택할 덩어리의 모양만 보관.
    hsv = cv2.cvtColor(frame[lane.ROI_TOP:lane.ROI_BOTTOM], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (15, 80, 100), (40, 255, 255))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
    parts = sorted((i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 50),
                   key=lambda i: (-stats[i, cv2.CC_STAT_AREA], centers[i, 0]))[:2]
    traces = []
    for i in parts:
        xs = np.nonzero(labels == i)[1]
        traces.append(dict(x=float(centers[i, 0]), area=int(stats[i, cv2.CC_STAT_AREA]),
                           bbox=tuple(int(v) for v in stats[i,:4]),
                           span=int(stats[i,cv2.CC_STAT_WIDTH]),
                           rise=int(stats[i,cv2.CC_STAT_HEIGHT]),
                           left_guide=float(np.percentile(xs, 15)),
                           right_guide=float(np.percentile(xs, 85))))
    lines['traces'] = sorted(traces, key=lambda trace: trace['x'])
    lines['corner_traces'] = lines['traces']
    lines['front_corner'] = any(t['span']>frame.shape[1]/2 and
                               t['span']>=CORNER_ASPECT_RATIO*t['rise'] for t in traces)
    lines['corner_white_ratio'] = corner_white_floor(frame)
    lines['corner_white_floor'] = lines['corner_white_ratio']>CORNER_WHITE_RATIO
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


def find_lane_dividers(frame):
    """2차선의 흰 중앙선 조각. 화살표/넓은 흰 바닥은 제외한다."""
    hsv = cv2.cvtColor(frame[lane.ROI_TOP:lane.ROI_BOTTOM], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 215), (179, 65, 255))
    yellow = cv2.inRange(hsv, (15, 80, 100), (40, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not 80 <= area <= 5000:
            continue
        hull = cv2.contourArea(cv2.convexHull(contour))
        if not hull or area / hull < .9:
            continue
        (x, y), (a, b), angle = cv2.minAreaRect(contour)
        if min(a, b) > 0 and max(a, b) / min(a, b) >= 4 and max(a, b) >= 40:
            xx, yy = round(x), round(y)
            column = yellow[:, max(0,xx-12):min(yellow.shape[1],xx+13)]
            if not np.any(column[:yy]) and np.any(column[yy:yy+40]):
                continue
            result.append(dict(x=float(x), y=float(y + lane.ROI_TOP), area=area))
    return result


def find_start_markers(frame):
    """흰 테두리 사이 START 다섯 글자의 배치와 A/R 구멍을 확인한다."""
    occupied = np.flatnonzero(np.any(frame != 0, axis=(1, 2)))
    bottom = int(occupied[-1]) + 1 if occupied.size else frame.shape[0]
    width = frame.shape[1]
    hsv = cv2.cvtColor(frame[:bottom], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 215), (179, 65, 255))
    mask[:int(bottom * .4)] = 0
    contours, tree = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    letters = []
    for i, contour in enumerate(contours):
        if tree[0, i, 3] != -1:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        hull = cv2.contourArea(cv2.convexHull(contour))
        solidity = cv2.contourArea(contour) / hull if hull else 1
        if (width * .015 < w < width * .18 and bottom * .018 < h < bottom * .16 and
                .8 < w / h < 9 and .4 < solidity < .86):
            letters.append((x, y, w, h, tree[0, i, 2] != -1))
    letters.sort()
    boxes = []
    groups = set()
    for sx, sy, sw, sh, hole in letters:
        row = [letter for letter in letters
               if abs(letter[1] + letter[3] / 2 - sy - sh / 2) < sh * 1.5 and
               .6 * sh < letter[3] < 1.6 * sh]
        groups.update(tuple(row[i:i+5]) for i in range(len(row) - 4))
    for group in sorted(groups):
        if not group[2][4] or not group[3][4]:
            continue
        xs = np.array([x + w / 2 for x, y, w, h, hole in group])
        ys = np.array([y + h / 2 for x, y, w, h, hole in group])
        height = float(np.median([h for x, y, w, h, hole in group]))
        if max(h for x, y, w, h, hole in group) > 1.6 * height:
            continue
        fitted = np.polyval(np.polyfit(xs, ys, 1), xs)
        if np.max(np.abs(fitted - ys)) > height * .3:
            continue
        if any(group[j+1][0] - (group[j][0] + group[j][2]) > height * 2 for j in range(4)):
            continue
        x1, x2 = group[0][0], group[-1][0] + group[-1][2]
        y1 = min(y for x, y, w, h, hole in group)
        y2 = max(y + h for x, y, w, h, hole in group)
        if x2 - x1 < width * .25:
            continue
        above = mask[max(0, int(y1 - 3 * height)):y1, x1:x2]
        below = mask[y2:min(bottom, int(y2 + 3 * height)), x1:x2]
        if (above.size and below.size and
                np.max(np.mean(above > 0, axis=1)) > .6 and
                np.max(np.mean(below > 0, axis=1)) > .6):
            boxes.append((x1, y1, x2 - x1, y2 - y1))
    return dict(visible=bool(boxes), near=any(y + h / 2 > bottom * .8 for x,y,w,h in boxes),
                boxes=boxes)


class MarkEvent:
    """하나의 바닥 표시를 여러 화면에서 중복 세지 않는다."""
    def __init__(self):
        self.since = None
        self.missing = None
        self.latched = False

    def update(self, present, now):
        if present:
            self.missing = None
            if self.since is None:
                self.since = now
            if not self.latched and now - self.since >= .2 - 1e-9:
                self.latched = True
                return True
        else:
            self.since = None
            if self.missing is None:
                self.missing = now
            if now - self.missing >= .5 - 1e-9:
                self.latched = False
        return False


class LaneController(lane.LaneController):
    """07의 추적·정지를 바탕으로 표식 순서와 선택한 선의 조향을 계산한다."""

    def __init__(self):
        super().__init__()
        self.floor_color = None
        self.color_missing_since = None
        self.base_speed = lane.BASE_SPEED
        self.slow_active = False
        self.slow_seen_since = None
        self.slow_end_since = None
        self.route_step = 1
        self.crossings = 0
        self.crossing_event = MarkEvent()
        self.rotary_event = MarkEvent()
        self.front_corner_event = MarkEvent()
        self.start_event = MarkEvent()
        self.slow_event = MarkEvent()
        self.start_passes = 0
        self.second_crossings = None
        self.route_leg = 'FRONT'
        self.choice = None
        self.choice_since = None
        self.choice_stable_since = None
        self.choice_end = None
        self.observed = None
        self.observed_at = None
        self.guide_center = None
        self.corner_direction = None
        self.corner_since = None
        self.corner_stable_since = None
        self.corner_armed = True
        self.corner_end = None
        self.corner_ended_at = None
        self.corner_cooldown_until = None
        self.corner_trace = None
        self.normal_widths = deque(maxlen=NORMAL_WIDTH_SAMPLES)
        self.reacquiring = False
        self.reacquire_stable_since = None
        self.departure_since = None
        self.departure_external = False
        self.departure_white_ratio = 0.

    def check_departure(self,lines,now):
        if lines is None:return
        self.departure_white_ratio = lines.get('corner_white_ratio',0)
        if self.stopped:return
        if self.departure_white_ratio>CORNER_WHITE_RATIO:
            if self.departure_since is None:self.departure_since = now
            if now-self.departure_since>=WHITE_DEPARTURE_SECONDS-1e-9:
                if self.corner_since is not None:self._end_corner(now,'LANE_DEPARTURE')
                self.stopped,self.state,self.speeds = True,'LANE_DEPARTURE',lane.STOP
        else:self.departure_since = None

    def _screen_lines(self,lines):
        result = dict(lines)
        traces = sorted(lines.get('traces',[]),key=lambda t:t['x'])
        result.update(left=None,right=None,left_count=0,right_count=0,unassigned=False)
        if len(traces)>=2:
            result.update(left=traces[0]['x'],right=traces[-1]['x'],
                          left_count=traces[0]['area'],right_count=traces[-1]['area'])
        elif traces:
            name = 'left' if traces[0]['x']<320 else 'right'
            result[name],result[name+'_count'] = traces[0]['x'],traces[0]['area']
        return result

    def _screen_single(self,lines):
        present = [(name,lines[name]) for name in ('left','right') if lines.get(name) is not None]
        if len(present)==1:
            old,x = present[0]
            name = 'left' if x<320 else 'right'
            count = lines.get(old+'_count',0)
            lines.update(left=None,right=None,left_count=0,right_count=0,unassigned=False)
            lines[name],lines[name+'_count'] = x,count
        return lines

    def _trusted_lines(self,lines):
        result = dict(lines)
        left,right = lines.get('left'),lines.get('right')
        result['width_rejected'] = False
        reference = float(np.median(self.normal_widths)) if self.normal_widths else self.width
        if left is not None and right is not None and reference is not None:
            observed = abs(right-left)
            if observed<reference*MIN_NORMAL_WIDTH_RATIO:
                keep = max(('left','right'),key=lambda name:lines.get(name+'_count',0))
                other = 'right' if keep=='left' else 'left'
                result[other],result[other+'_count'] = None,0
                traces = lines.get('traces',[])
                result['traces'] = [max(traces,key=lambda t:t['area'])] if traces else []
                result['width_rejected'] = True
                result['rejected_width'] = observed
        if (left is not None and right is not None and not result['width_rejected'] and
                not lines.get('front_corner') and self.corner_since is None):
            self.normal_widths.append(abs(right-left))
        return result

    def _end_corner(self,now,reason):
        self.corner_end = reason
        self.corner_ended_at = now
        self.corner_cooldown_until = now+CORNER_COOLDOWN_SECONDS
        self.corner_direction,self.corner_since,self.corner_stable_since = None,None,None
        self.corner_trace = None
        self.corner_armed = False
        self.previous = None
        self.observed,self.observed_at = None,None
        self.reacquiring = True
        self.reacquire_stable_since = None

    def _corner(self,lines,now):
        horizontal = lines.get('front_corner',False)
        if not horizontal:self.corner_armed = True
        direction = CORNER_DIRECTIONS.get(self.route_step)
        if self.choice is not None or direction is None or self.stopped:
            if self.corner_since is not None:self._end_corner(now,'EXCLUDED_OR_STOPPED')
            return
        if lines.get('corner_white_floor'):
            if self.corner_since is not None:self._end_corner(now,'WHITE_FLOOR')
            return
        cooldown = self.corner_cooldown_until is not None and now<self.corner_cooldown_until
        if self.corner_since is None and horizontal and self.corner_armed and not cooldown:
            self.corner_since = now
            self.corner_direction = direction
            self.corner_stable_since = None
            self.corner_end = None
            self.corner_armed = False
        if self.corner_since is None:return
        self.last_turn = self.corner_direction
        self.state = 'CORNER_'+self.corner_direction
        self.speeds = (55,55,5,5) if self.corner_direction=='RIGHT' else (5,5,55,55)

    def _choose(self, direction, now):
        self.choice = direction
        self.choice_since = now
        self.choice_stable_since = None
        self.choice_end = None

    def _route(self, lines, now):
        mark = lines.get('slow', {})
        traces = lines.get('traces', [])
        crossing = self.crossing_event.update(mark.get('crossing_near', False), now)
        rotary = self.rotary_event.update(mark.get('roundabout_near', False), now)
        self.slow_event.update(mark.get('text', False), now)
        start = lines.get('start', {})
        self.start_event.update(start.get('visible', False), now)
        if self.start_event.latched and start.get('near'):
            if self.route_step in (5, 6) and self.start_passes == 0:
                self.start_passes = 1
            elif self.route_step == 12 and self.start_passes == 1:
                self.start_passes = 2
                self.stopped = True
                self.state = 'FINISH'
                self.speeds = lane.STOP
                return
        if crossing:
            self.crossings += 1
        if self.route_step == 1 and self.crossings >= 2:
            if self.front_corner_event.update(len(traces) == 2 and traces[0]['x'] > 140, now):
                self.route_step = 2
        elif self.route_step == 2 and crossing:
            self.route_step = 3
        elif self.route_step == 3 and crossing and self.choice is None:
            self._choose('RIGHT', now)
        elif self.route_step == 4 and self.choice is None:
            if self.route_leg == 'WAIT_ROTARY' and rotary:
                self.route_leg = 'CIRCLE'
                self._choose('LEFT', now)
            elif (self.route_leg == 'EXIT_WAIT' and not self.rotary_event.latched and
                  self.center is not None and self.center > 360):
                self.route_leg = 'EXIT'
                self._choose('RIGHT', now)
        elif self.route_step == 5 and self.start_event.latched:
            self.route_step = 6
            self.route_leg = 'SECOND_FRONT'
            self.second_crossings = self.crossings
        elif (self.route_step == 6 and crossing and self.choice is None and
              self.crossings - self.second_crossings >= 2):
            self.route_leg = 'SIDE_ROAD'
            self._choose('RIGHT', now)
        elif self.route_step == 7 and self.choice is None:
            if self.route_leg == 'WAIT_ROTARY' and self.rotary_event.latched:
                self.route_leg = 'CIRCLE'
                self._choose('LEFT', now)
            elif self.route_leg == 'EXIT_WAIT' and self.slow_event.latched:
                self.route_step = 8
                self.route_leg = 'SLOW_RETURN'
        elif self.route_step == 8 and not self.slow_active and not mark.get('text'):
            self.route_step = 9
            self.route_leg = 'UPPER_CORNERS'
        elif self.route_step == 9 and lines.get('floor', {}).get('color') == 'blue':
            self.route_step = 10
            self.route_leg = 'BLUE'
        elif self.route_step == 10 and lines.get('floor', {}).get('color') == 'red':
            self.route_step = 11
            self.route_leg = 'RED'
        elif (self.route_step == 11 and self.floor_color is None and
              lines.get('floor', {}).get('color') is None):
            self.route_step = 12
            self.route_leg = 'FINAL_CORNERS'

        if self.choice is not None:
            traces = lines.get('traces', [])
            stable = (len(traces) == 2 and traces[1]['x'] - traces[0]['x'] >= 300)
            if stable and self.observed is not None:
                dt = now - self.observed_at
                stable = all(abs(traces[i]['x'] - self.observed[i]) <= 250 * dt
                             for i in range(2))
            else:
                stable = False
            if stable:
                if self.choice_stable_since is None:
                    self.choice_stable_since = now
            else:
                self.choice_stable_since = None
            finished = (self.choice_stable_since is not None and
                        now - self.choice_stable_since > .5 + 1e-9)
            if finished or now - self.choice_since >= 4 - 1e-9:
                self.choice_end = 'BOTH_STABLE' if finished else 'LIMIT4S'
                self.choice = None
                if self.route_step == 3:
                    self.route_step = 4
                    self.route_leg = 'WAIT_ROTARY'
                elif self.route_step == 4 and self.route_leg == 'CIRCLE':
                    self.route_leg = 'EXIT_WAIT'
                elif self.route_step == 4 and self.route_leg == 'EXIT':
                    self.route_step = 5
                    self.route_leg = 'TWO_LANE'
                elif self.route_step == 6:
                    self.route_step = 7
                    self.route_leg = 'WAIT_ROTARY'
                elif self.route_step == 7 and self.route_leg == 'CIRCLE':
                    self.route_leg = 'EXIT_WAIT'
        traces = lines.get('traces', [])
        self.observed = [trace['x'] for trace in traces] if len(traces) == 2 else None
        self.observed_at = now

    def _route_center(self, lines):
        traces = lines.get('traces', [])
        if not traces:
            return None
        if self.choice == 'RIGHT':
            return traces[-1]['right_guide']
        if self.choice == 'LEFT':
            return traces[0]['left_guide']
        if self.reacquiring:return None
        if self.route_step in (1, 3, 6):
            return traces[0]['x'] + 250 if len(traces) == 2 else None
        if self.route_step == 5:
            dividers = [d for d in lines.get('dividers', []) if d['x'] < traces[-1]['x'] - 40]
            if dividers:
                divider = max(dividers, key=lambda d: d['area'])
                return (divider['x'] + traces[-1]['x']) / 2
        return None

    def update(self, lines, now):
        if not self.departure_external:self.check_departure(lines,now)
        if self.stopped:return lane.STOP
        if self.corner_since is not None:
            if lines.get('corner_white_floor'):self._end_corner(now,'WHITE_FLOOR')
            elif now-self.corner_since>=CORNER_HOLD_SECONDS-1e-9:self._end_corner(now,'FIXED1.3S')
        if self.reacquiring:lines = self._screen_lines(lines)
        lines = self._trusted_lines(lines)
        if self.reacquiring:
            lines = self._screen_single(lines)
            normal = lines.get('left') is not None and lines.get('right') is not None and not lines.get('width_rejected')
            if normal:
                if self.reacquire_stable_since is None:self.reacquire_stable_since = now
                if now-self.reacquire_stable_since>CORNER_REACQUIRE_SECONDS+1e-9:self.reacquiring = False
            else:self.reacquire_stable_since = None
        speeds = super().update(lines, now)
        if self.normal_widths:self.width = float(np.median(self.normal_widths))
        # 관측하지 않은 반대쪽의 오래된 x가 한 선의 좌우 이름을 빼앗지 않게 한다.
        # 실제 lines의 None은 유지하므로 두 선 확인/종료 조건에 가상 선은 쓰이지 않는다.
        if self.previous is not None and self.width is not None:
            if lines.get('left') is not None and lines.get('right') is None:
                self.previous = dict(left=lines['left'],right=lines['left']+self.width)
            elif lines.get('right') is not None and lines.get('left') is None:
                self.previous = dict(left=lines['right']-self.width,right=lines['right'])
        if not self.stopped:
            self._route(lines, now)
        self.guide_center = self._route_center(lines)
        if self.guide_center is not None and self.state.startswith('TRACK') and not self.stopped:
            speeds = lane.wheel_speeds(self.guide_center)
            self.speeds = speeds
            if speeds[0] != speeds[2]:
                self.last_turn = 'RIGHT' if speeds[0] > speeds[2] else 'LEFT'
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
        if self.slow_active or self.route_step == 8 or (self.route_step == 3 and self.choice == 'RIGHT'):
            self.base_speed = 25
        if self.state in ('TRACKBOTH', 'TRACKLEFT', 'TRACKRIGHT') and not self.stopped:
            offset = self.base_speed - lane.BASE_SPEED
            self.speeds = tuple(max(0, min(lane.MAX_SPEED, v + offset)) for v in speeds)
            if self.guide_center is not None:
                # 경로 선택의 큰 조향에서도 한쪽0 제한 때문에 평균 속도가 올라가지 않게 한다.
                limit = min(self.base_speed, lane.MAX_SPEED - self.base_speed)
                turn = max(-limit, min(limit, round((speeds[0] - speeds[2]) / 2)))
                left, right = self.base_speed + turn, self.base_speed - turn
                self.speeds = (left, left, right, right)
        self._corner(lines,now)
        if self.reacquiring:self.previous = None
        return self.speeds

    def report(self):
        return dict(super().report(), floor_color=self.floor_color,
                    base_speed=self.base_speed, slow_active=self.slow_active,
                    route_step=self.route_step, choice=self.choice,
                    route_leg=self.route_leg,
                    choice_end=self.choice_end, guide_center=self.guide_center,
                    crossings=self.crossings, start_passes=self.start_passes,
                    corner_direction=self.corner_direction,corner_since=self.corner_since,
                    corner_end=self.corner_end,corner_ended_at=self.corner_ended_at,
                    corner_cooldown_until=self.corner_cooldown_until,
                    corner_white_ratio=self.departure_white_ratio,
                    reacquiring=self.reacquiring,reacquire_stable_since=self.reacquire_stable_since,
                    departure_since=self.departure_since)


def lane_context(frame):
    """④ 안전 판정 문맥. 원본의 위280행을 복사해 ①②③ 표시 영역과 맞춘다."""
    frame = marker_frame(frame)
    occupied = np.flatnonzero(np.any(frame != 0, axis=(1, 2)))
    height = int(occupied[-1]) + 1 if occupied.size else frame.shape[0]
    hsv = cv2.cvtColor(frame[:height],cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,(15,80,100),(40,255,255))
    # 640폭에서 실제 노란 띠보다 가는 1~4px 안내선/글자 획을 제외한다.
    mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((1,6),np.uint8))
    segments = cv2.HoughLinesP(mask,1,np.pi/180,20,minLineLength=30,maxLineGap=25)
    segments = [] if segments is None else segments[:,0].tolist()
    slopes = [[],[]]
    for x1,y1,x2,y2 in segments:
        if abs(y2-y1)<12:continue
        a = (x2-x1)/(y2-y1)
        if abs(a)<.2:continue
        slopes[0 if a<0 else 1].append((a,x1-a*y1))
    horizon = None
    if all(slopes):
        al,bl = np.median(slopes[0],axis=0)
        ar,br = np.median(slopes[1],axis=0)
        vy = (br-bl)/(al-ar)
        vx = al*vy+bl
        if 0<=vy<height*.5 and 0<=vx<=frame.shape[1]:horizon = float(vy)
    ys = np.nonzero(mask[lane.ROI_TOP:min(height,lane.ROI_BOTTOM)])[0]
    width_y = float(np.mean(ys)+lane.ROI_TOP) if len(ys) else (lane.ROI_TOP+lane.ROI_BOTTOM)/2
    # 트랙 뒤 검은 턱 아래에서 바닥으로 밝아지는 넓은 경계만 근거로 쓴다.
    # 작은 사람/책상/영상 안내선은 화면 중앙80%의 행 중앙값에 영향을 덜 준다.
    road_top = None
    tops = [min(y1,y2) for x1,y1,x2,y2 in segments if abs(y2-y1)>=12]
    values = np.median(hsv[:,frame.shape[1]//10:frame.shape[1]*9//10,2],axis=1)
    edges = []
    if tops:
        for row in range(10,int(height*.65)-10):
            if abs(row-min(tops))>height*.25:continue
            above = float(np.median(values[row-8:row-2]))
            below = float(np.median(values[row+2:row+10]))
            if above<=60 and below>=90 and below-above>=50:
                edges.append((below-above,-row))
        if edges:road_top = -max(edges)[1]
    dark_floor = ((hsv[:,:,1]<=100)&(hsv[:,:,2]<=180)).astype(np.uint8)
    dark_floor.setflags(write=False)
    mask.setflags(write=False)
    return dict(height=height,width=frame.shape[1],yellow=mask,segments=segments,
                horizon=horizon,width_y=width_y,road_top=road_top,dark_floor=dark_floor)


def foot_on_lane(box, context, lane_width=None, center=320, horizon=None):
    """발 높이의 두 노란 경계를 사용한다. 한쪽만 있으면07 폭, 없으면 가운데 절반."""
    x,y,w,h = map(float,box)
    fx,fy = x+w/2,y+h
    result = dict(foot=[fx,fy],near=fy>context['height']*.25,inside=False,
                  bounds=None,basis='far',offroad_reason=None,
                  road_top=context.get('road_top'),horizon=context.get('horizon'),
                  ground_dark_ratio=None)
    if not result['near']:
        return result
    # 현재 화면에 근거가 있을 때만 제외한다. 오래된 소실점으로 사람을 무시하지 않는다.
    if context.get('road_top') is not None and fy<context['road_top']:
        result.update(basis='offroad',offroad_reason='above_road_end')
        return result
    if context.get('horizon') is not None and fy<context['horizon']:
        result.update(basis='offroad',offroad_reason='above_vanishing_point')
        return result
    floor = context.get('dark_floor')
    if floor is not None:
        below = floor[max(0,round(fy)+2):min(context['height'],round(fy)+14),
                      max(0,round(fx)-8):min(context['width'],round(fx)+9)]
        if below.size:
            result['ground_dark_ratio'] = float(np.mean(below))
            if result['ground_dark_ratio']<.2:
                result.update(basis='offroad',offroad_reason='not_black_floor')
                return result
    row = max(0,min(context['height']-1,round(fy)))
    mask = context['yellow']
    xs = np.flatnonzero(np.any(mask[max(0,row-2):min(len(mask),row+3)]>0,axis=0))
    parts = np.split(xs,np.flatnonzero(np.diff(xs)>3)+1) if xs.size else []
    points = [float(np.mean(part)) for part in parts if len(part)>=6]
    # 흰 횡단보도/물체에 가린 발 높이도 주변 실제 노란 띠의 기울기로 잰다.
    # 발 높이와 세로120px(480높이 기준) 이내인 실제 띠만 연장한다.
    projected = []
    for x1,y1,x2,y2 in context.get('segments',[]):
        if abs(y2-y1)<12:continue
        if not min(y1,y2)-context['height']*.25<=row<=max(y1,y2)+context['height']*.25:continue
        projected.append(x1+(row-y1)*(x2-x1)/(y2-y1))
    if projected:
        estimates = np.array(sorted(projected+points))
        clusters = np.split(estimates,np.flatnonzero(np.diff(estimates)>context['width']*.03)+1)
        points = [float(np.median(cluster)) for cluster in clusters]
    if len(points)>=2:
        # 갈림길의 다른 노란 선을 포함하지 않게 주행 가이드에 가장 가까운 인접 경계 쌍.
        left,right = min(zip(points,points[1:]),key=lambda pair:abs((pair[0]+pair[1])/2-center))
        basis = 'two_lines'
    elif len(points)==1 and lane_width is not None and math.isfinite(lane_width) and lane_width>0:
        # 07 폭은120~300행의 평균이다. 발 높이로 원근 보정한 뒤 사용한다.
        vy = context.get('horizon') if context.get('horizon') is not None else horizon
        if vy is not None and context['width_y']>vy and fy>vy:
            lane_width *= (fy-vy)/(context['width_y']-vy)
        if points[0]<center:left,right = points[0],points[0]+lane_width
        else:left,right = points[0]-lane_width,points[0]
        basis = 'one_line_07_width'
    else:
        left,right = context['width']*.25,context['width']*.75
        basis = '선 없음-가운데 기준'
    # '노란 선 사이'는 띠의 안쪽 가장자리다. 띠 자체는 차선 내부가 아니다.
    if basis=='two_lines' or basis=='one_line_07_width':
        widths = [len(part) for part in parts if len(part)>=6]
        margin = float(np.median(widths)/2) if widths else 4.
        left,right = left+margin,right-margin
    result.update(bounds=[left,right],basis=basis,inside=left<=fx<=right)
    return result


class FullCourseVisionWorker(reactions.VisionWorker):
    """06의 최신결과 공유/시작/종료를 재사용. 320모델과0.3 사람 문턱만 어댑터로 확장."""
    def __init__(self,camera,detector=None,clock=time.monotonic):
        super().__init__(camera,detector)
        self.clock = clock
        self.thread.name = 'full-course-yolo320'
        self.inference_count = 0

    def run(self):
        previous = None
        try:
            detector = self.detector if self.detector is not None else reactions.signs.Detector(size=320,conf=.3)
            while not self.stop.is_set():
                frame,sequence = self.camera.snapshot()
                if sequence==previous:
                    self.stop.wait(.005)
                    continue
                captured_at = self.clock()
                raw = detector(frame)
                found = [(name,float(score),tuple(box)) for name,score,box in raw
                         if name in ('person','stop sign') and math.isfinite(score)
                         and score>=(.3 if name=='person' else .4)
                         and len(box)==4 and all(math.isfinite(v) for v in box) and box[2]>0 and box[3]>0]
                context = lane_context(frame)
                with self.lock:
                    self.inference_count += 1
                    self.latest = dict(sequence=sequence,captured_at=captured_at,
                                       completed_at=self.clock(),found=found,context=context)
                previous = sequence
        except Exception as exc:
            self.error = exc


class SafetyController:
    """06의 확인/부재1초/STOP3초/재출발후5초,04의중앙값·오류처리를 조합한다."""
    def __init__(self,require_distance=True):
        self.signs = reactions.SignController()
        self.obstacle = obstacles.ObstacleController()
        self.require_distance = require_distance
        self.sequence = None
        self.hits = {name:deque() for name in ('person','stop sign')}
        self.people = []
        self.stop_boxes = []
        self.person_since = None
        self.person_locked = False
        self.state = 'WAITVISION'
        self.blocked = True
        self.fresh = False
        self.age = None
        self.distance_error = None
        self.horizon = None

    def observe_distance(self,distance_cm,now=None,error=None):
        self.distance_error = error
        # 04의50은 쓰지 않는다. moving/중앙값/오류 상태만 안전 스위치로 사용.
        self.obstacle.update(distance_cm)

    def step(self,result,now,lane_width=None,center=320):
        self.age = None if result is None else now-result['captured_at']
        self.fresh = result is not None and 0<=self.age<=.5
        if self.fresh and result['sequence']!=self.sequence:
            self.sequence = result['sequence']
            self.people,self.stop_boxes = [],[]
            eligible = {}
            if result['context'].get('horizon') is not None:self.horizon = result['context']['horizon']
            for name,score,box in result['found']:
                if name not in self.hits or not math.isfinite(score):continue
                if len(box)!=4 or not all(math.isfinite(v) for v in box) or box[2]<=0 or box[3]<=0:continue
                if name=='person' and score>=.3:
                    person = dict(score=float(score),box=list(box),**foot_on_lane(box,result['context'],lane_width,center,self.horizon))
                    self.people.append(person)
                    if person['near'] and person['inside']:eligible.setdefault(name,(score,box))
                elif name=='stop sign' and score>=.4:
                    near = box[3]>=result['context']['height']*.08
                    self.stop_boxes.append(dict(score=float(score),box=list(box),near=near))
                    if near:eligible.setdefault(name,(score,box))
            passed = []
            for name,history in self.hits.items():
                while history and result['captured_at']-history[0]>.5+1e-9:history.popleft()
                if name in eligible:
                    score,box = eligible[name]
                    history.append(result['captured_at'])
                    self.signs.counts[name] = 1 if len(history)>=2 else 0
                    # 06에는 "13의 사전 조건을 통과한 목표가 있음"을 전달한다.
                    # 이 내부1.0은 원래 확률이 아니다. 실제 YOLO 점수는 people/stop_boxes에 그대로 기록한다.
                    passed.append((name,1.,box))
                else:self.signs.counts[name] = 0
            self.signs.observe(dict(sequence=self.sequence,found=passed),now)
        elif not self.fresh:
            self.signs.invalidate()
            for history in self.hits.values():history.clear()

        if self.signs.person:
            if self.person_since is None:self.person_since = now
            if now-self.person_since>15:self.person_locked = True
        elif not self.person_locked:self.person_since = None

        if self.person_locked:self.state = 'PERSON_CHECK15'
        elif not self.fresh:self.state = 'WAITVISION' if result is None else 'STALEVISION'
        elif self.signs.person:self.state = 'PERSONWAIT'
        elif self.signs.stop_pending or (self.signs.stop_until is not None and now<self.signs.stop_until):
            self.state = 'STOPWAIT'
        elif self.require_distance and not self.obstacle.moving:
            self.state = 'ULTRA_ERROR' if self.obstacle.invalid_count>=3 else 'OBSTACLEWAIT'
        else:self.state = 'CLEAR'
        self.blocked = self.state!='CLEAR'
        return self.blocked

    def motor_sent(self,speeds,now):
        self.signs.motor_sent(speeds,now)

    def report(self):
        messages = dict(PERSONWAIT='사람 대기',PERSON_CHECK15='사람 대기 15초 — 확인 필요',
                        STOPWAIT='STOP 3초 정지',OBSTACLEWAIT='초음파 정지/대기',
                        ULTRA_ERROR='초음파 오류 3번 — 정지',WAITVISION='인식 결과 대기',
                        STALEVISION='오래된 인식 결과 — 정지',CLEAR='주행')
        message = messages[self.state]
        if any(person['basis']=='선 없음-가운데 기준' for person in self.people):
            message += ' / 선 없음-가운데 기준'
        outside = dict(above_road_end='도로 끝 위',above_vanishing_point='소실점 위',
                       not_black_floor='발밑 검은 바닥 없음')
        reasons = sorted({outside[p['offroad_reason']] for p in self.people if p.get('offroad_reason')})
        if reasons:message += ' / 트랙 밖: '+', '.join(reasons)
        return dict(safety_state=self.state,safety_message=message,blocked=self.blocked,
                    vision_fresh=self.fresh,vision_age=self.age,person=self.people,stop_boxes=self.stop_boxes,
                    person_locked=self.person_locked,person_since=self.person_since,
                    stop_until=self.signs.stop_until,ignore_until=self.signs.ignore_until,
                    distance_cm=self.obstacle.filtered_cm,ultra_state=self.obstacle.status,
                    ultra_invalid_count=self.obstacle.invalid_count,distance_error=self.distance_error)


class FullCourseController:
    """기존LaneController를 그대로 감싼④. 모든 대기의 합집합만큼 경로 시계를 멈춘다."""
    def __init__(self,vision_worker=None,require_distance=True):
        self.route = LaneController()
        self.route.departure_external = True
        self.safety = SafetyController(require_distance)
        self.vision_worker = vision_worker
        self.last_wall = None
        self.paused_seconds = 0.
        self.was_blocked = False
        self.route_now = None
        self.speeds = lane.STOP

    @property
    def previous(self):return self.route.previous
    @property
    def width(self):return self.route.width
    @property
    def stopped(self):return self.route.stopped

    def observe_distance(self,distance_cm,now=None,error=None):
        self.safety.observe_distance(distance_cm,now,error)

    def update(self,lines,now,vision=None,*,new_frame=True):
        if new_frame:self.route.check_departure(lines,now)
        if self.vision_worker is not None:vision = self.vision_worker.snapshot()
        center = self.route.guide_center if self.route.guide_center is not None else self.route.center
        blocked = self.safety.step(vision,now,self.route.width,320 if center is None else center)
        if self.last_wall is not None:
            if now<self.last_wall:raise ValueError('시각은 뒤로 갈 수 없습니다')
            if self.was_blocked:self.paused_seconds += now-self.last_wall
        self.last_wall,self.was_blocked = now,blocked
        self.route_now = now-self.paused_seconds
        if blocked:self.speeds = lane.STOP
        elif new_frame:self.speeds = self.route.update(lines,self.route_now)
        else:self.speeds = self.route.tick(self.route_now)
        return self.speeds

    def motor_sent(self,speeds,now):
        self.safety.motor_sent(speeds,now)

    def report(self):
        result = self.route.report()
        result.update(route_state=result['state'],speeds=self.speeds,route_clock=self.route_now,
                      paused_seconds=self.paused_seconds,**self.safety.report())
        if self.safety.blocked:result['state'] = self.safety.state
        if self.route.state=='LANE_DEPARTURE':
            result.update(state='LANE_DEPARTURE',safety_message='차선 벗어남')
        return result


def safety_annotated(frame,report):
    out = lane.annotated(frame,report)
    for person in report['person']:
        x,y,w,h = map(round,person['box'])
        color = (0,0,255) if person['inside'] and person['near'] else (0,255,0)
        cv2.rectangle(out,(x,y),(x+w,y+h),color,2)
        fx,fy = map(round,person['foot'])
        cv2.circle(out,(fx,fy),4,color,-1)
        if person['bounds'] is not None:
            left,right = map(round,person['bounds'])
            cv2.line(out,(left,fy),(right,fy),(255,0,255),2)
        cv2.putText(out,f"PERSON {person['score']:.2f} FOOT {fx},{fy} IN {person['inside']}",(max(0,x),max(12,y-4)),
                    cv2.FONT_HERSHEY_SIMPLEX,.42,color,1)
        if person.get('offroad_reason'):
            cv2.putText(out,person['offroad_reason'].upper(),(max(0,x),min(len(out)-4,y+h+12)),
                        cv2.FONT_HERSHEY_SIMPLEX,.36,color,1)
    fallback = any(p['basis']=='선 없음-가운데 기준' for p in report['person'])
    info = f"{report['safety_state']} DIST {report['distance_cm']} STEP {report['route_step']}"
    cv2.putText(out,info,(8,390),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
    for stop in report['stop_boxes']:
        x,y,w,h = map(round,stop['box'])
        cv2.rectangle(out,(x,y),(x+w,y+h),(0,0,255),2)
        cv2.putText(out,f"STOP {stop['score']:.2f}",(x,max(12,y-4)),cv2.FONT_HERSHEY_SIMPLEX,.42,(0,0,255),1)
    if fallback:cv2.putText(out,'NO LINES: CENTER HALF',(8,420),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
    if report.get('corner_end'):
        cv2.putText(out,f"CORNER END {report['corner_end']} WHITE {report.get('corner_white_ratio',0):.2f}",
                    (8,450),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
    return out


class FullCourseRecorder:
    """같은 장면을 원본/표시 영상 두 파일에 바로 쓰는 별도 스레드."""
    def __init__(self,camera,output_dir=None,writer_factory=None):
        self.camera = camera
        root = Path(__file__).resolve().parents[1]/'results/videos'
        self.output_dir = root if output_dir is None else Path(output_dir).resolve()
        if not self.output_dir.is_relative_to(root):
            raise ValueError('녹화는 results/videos/ 안에 저장합니다')
        stamp = datetime.now(lane.KST).strftime('%Y%m%d_%H%M%S_%f')
        self.paths = {kind:self.output_dir/f'{kind}_{stamp}.mp4' for kind in ('raw','blackbox')}
        self.writer_factory = cv2.VideoWriter if writer_factory is None else writer_factory
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest_report = None
        self.error = None
        self.saved_frames = 0
        self.repeated_frames = 0
        self.thread = threading.Thread(target=self.run,name='full-course-video',daemon=True)

    def update(self,report):
        with self.lock:self.latest_report = dict(report)

    def start(self):
        self.thread.start()
        return self

    def check(self):
        if self.error is not None:raise RuntimeError('원본/블랙박스 녹화 오류') from self.error

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:self.thread.join(timeout=2)
        if self.thread.is_alive():raise RuntimeError('영상 녹화 종료 응답 없음')
        self.check()

    def run(self):
        writers = {}
        previous = None
        try:
            self.output_dir.mkdir(parents=True,exist_ok=True)
            began = time.monotonic()
            while not self.stop.is_set():
                if self.stop.wait(max(0,began+self.saved_frames/lane.video.FPS-time.monotonic())):break
                frame,sequence = self.camera.snapshot()
                raw = frame.copy()
                if not writers:
                    for kind,path in self.paths.items():
                        writer = self.writer_factory(str(path),cv2.VideoWriter_fourcc(*'avc1'),
                                                     lane.video.FPS,(raw.shape[1],raw.shape[0]))
                        writers[kind] = writer
                        if not writer.isOpened():raise RuntimeError(f'H.264 영상 저장 실패: {path}')
                # 영역 마스크/선/글자/시각을 전혀 넣지 않은 원본을 먼저 쓴다.
                writers['raw'].write(raw)
                with self.lock:report = self.latest_report
                marked = raw.copy() if report is None else safety_annotated(raw,report)
                stamp = datetime.now(lane.KST).strftime('%Y-%m-%d %H:%M:%S')
                cv2.putText(marked,stamp,(12,28),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
                writers['blackbox'].write(marked)
                self.saved_frames += 1
                self.repeated_frames += int(sequence==previous)
                previous = sequence
        except Exception as exc:self.error = exc
        finally:
            for writer in writers.values():writer.release()


def distance_for_obstacle(raw_cm):
    """13의 먼 거리만04의 유효 상한으로 제한한다. 원시값/읽기 오류는 따로 보존."""
    if isinstance(raw_cm,(int,float)) and math.isfinite(raw_cm) and raw_cm>400:
        return 400.
    return raw_cm


def run_safety_loop(camera,vision_worker,distance_read,key_pressed,stream,on_speeds,display=None,*,recorder=None,on_report=None,on_stop=None):
    """④의조합반복. 장치 생성/서보/바퀴/부저 호출 없음. on_speeds에계산값을전달한다.

    실물연결시는호출자가준비확인/초음파활성화/실제전송/최종네바퀴0을책임진다.
    주행루프에는추론호출이없고06에서재사용한worker.snapshot만읽는다.
    """
    controller = FullCourseController(vision_worker)
    recorder = FullCourseRecorder(camera) if recorder is None else recorder
    writer = csv.writer(stream,lineterminator='\n')
    writer.writerow(('wall_seconds','route_step','start_passes','state','speeds','safety_message',
                     'person_score_feet_inside','stop_boxes','ultra_cm','ultra_errors','paused_seconds',
                     'raw_ultra_cm','ultra_read_error','lane_frames',
                     'corner_direction','corner_since','corner_end','corner_ended_at','corner_cooldown_until','corner_white_ratio',
                     'left_line_x','right_line_x','lane_width','guide_center','reacquiring','departure_since'))
    sequence = None
    lines = None
    frame = None
    next_distance = time.monotonic()
    last_message = None
    lane_frames = 0
    raw_distance = None
    distance_read_error = None
    try:
        recorder.start()
        while not key_pressed():
            recorder.check()
            now = time.monotonic()
            if now>=next_distance:
                try:
                    raw_distance = distance_read()
                    distance_read_error = None
                    controller.observe_distance(distance_for_obstacle(raw_distance),now)
                except Exception as exc:
                    raw_distance,distance_read_error = None,str(exc)
                    controller.observe_distance(None,now,str(exc))
                next_distance = now+obstacles.INTERVAL
            candidate,new_sequence = camera.snapshot()
            fresh_frame = sequence!=new_sequence
            if fresh_frame:
                frame,sequence = candidate,new_sequence
                lines = find_lines(frame,controller.previous,controller.width)
                lane_frames += 1
            speeds = controller.update(lines,time.monotonic(),new_frame=fresh_frame)
            if key_pressed():break
            on_speeds(speeds)
            controller.motor_sent(speeds,time.monotonic())
            report = controller.report()
            report['runtime_lane_frames'] = lane_frames
            report['raw_distance_cm'] = raw_distance
            report['distance_read_error'] = distance_read_error
            if on_report is not None:on_report(report)
            recorder.update(report)
            if report['safety_message']!=last_message:
                print(report['safety_message'],flush=True)
                last_message = report['safety_message']
            writer.writerow((now,report['route_step'],report['start_passes'],report['state'],speeds,
                             report['safety_message'],json.dumps(report['person'],ensure_ascii=False),
                             json.dumps(report['stop_boxes']),report['distance_cm'],report['ultra_invalid_count'],
                             report['paused_seconds'],raw_distance,distance_read_error,lane_frames,
                             report['corner_direction'],report['corner_since'],report['corner_end'],
                             report['corner_ended_at'],report['corner_cooldown_until'],report['corner_white_ratio'],
                             report['left'],report['right'],report['width'],report['guide_center'],report['reacquiring'],report['departure_since']))
            stream.flush()
            if display is not None:display(safety_annotated(frame,report),report)
            if controller.stopped:break
            time.sleep(.005)
    finally:
        try:
            if on_stop is None:on_speeds(lane.STOP)
            else:on_stop()
        finally:recorder.close()
    return controller.report()


def prepare_camera(bot):
    """출발 준비에서 last.json 또는80/5 적용만 한다. 영상 보정은14번 몫."""
    spec = importlib.util.spec_from_file_location(
        'full_course_camera_pose',Path(__file__).with_name('14_camera_align.py'))
    camera_align = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(camera_align)
    return camera_align.restore_saved_pose(bot)


def checked_driver_call(function,*args):
    captured = io.StringIO()
    with redirect_stdout(captured):result = function(*args)
    output = captured.getvalue()
    if output:print(output,end='',flush=True)
    if 'i2c error' in output.casefold():raise RuntimeError('I2C error — 선/확장보드 전원을 확인하세요')
    return result


class MotorOutput:
    """04의 재전송/바퀴간 간격. check는0 명령도 보내지 않는다."""
    def __init__(self,bot,check=False,*,clock=time.monotonic,sleep_fn=time.sleep):
        self.bot,self.check = bot,check
        self.clock,self.sleep = clock,sleep_fn
        self.previous = None
        self.sent_at = None
        self.commands = 0
        self.batches = 0
        self.closed = False

    def __call__(self,speeds):
        if self.check or self.closed:return
        speeds = tuple(max(-lane.MAX_SPEED,min(lane.MAX_SPEED,int(v))) for v in speeds)
        if len(speeds)!=4:raise ValueError('바퀴 값은4개여야 합니다')
        now = self.clock()
        if speeds==self.previous and self.sent_at is not None and now-self.sent_at<obstacles.MOTOR_REFRESH:return
        self.sent_at = now
        for number,value in enumerate(speeds):
            checked_driver_call(self.bot.Ctrl_Muto,number,value)
            self.commands += 1
            if number<3:self.sleep(obstacles.MOTOR_GAP)
        self.batches += 1
        self.previous = speeds

    def close(self):
        if self.closed:return
        self.closed = True
        if self.check:return
        errors = []
        for repeat in range(obstacles.STOP_REPEATS):
            began = self.clock()
            for number in range(4):
                try:
                    checked_driver_call(self.bot.Ctrl_Muto,number,0)
                    self.commands += 1
                except (Exception,KeyboardInterrupt) as exc:errors.append(str(exc))
                if number<3:
                    try:self.sleep(obstacles.MOTOR_GAP)
                    except KeyboardInterrupt:pass
            self.batches += 1
            if repeat<obstacles.STOP_REPEATS-1:
                try:self.sleep(max(0,began+obstacles.MOTOR_REFRESH-self.clock()))
                except KeyboardInterrupt:pass
        if errors:raise RuntimeError('정지 실패: '+'; '.join(errors))


def cpu_temperature():
    try:return float(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
    except (OSError,ValueError):return None


class RuntimeMonitor:
    def __init__(self,vision,check):
        self.vision,self.check = vision,check
        self.started = self.last_time = time.monotonic()
        self.first_vision = self.last_vision = vision.inference_count
        self.last_lane = 0
        self.report = None
        self.samples = []
        self.initial_temperature = cpu_temperature()
        self.finished = None
        self.final_vision = None
        self.final_temperature = None

    def finish(self):
        if self.finished is None:
            self.finished = time.monotonic()
            self.final_vision = self.vision.inference_count
            self.final_temperature = cpu_temperature()

    def update(self,report):
        self.report = dict(report)
        now = time.monotonic()
        elapsed = now-self.last_time
        if elapsed<1:return
        count = self.vision.inference_count
        sample = dict(seconds=now-self.started,
                      lane_hz=(report['runtime_lane_frames']-self.last_lane)/elapsed,
                      yolo_hz=(count-self.last_vision)/elapsed,cpu_c=cpu_temperature(),
                      speeds=list(report['speeds']),route_step=report['route_step'],reason=report['safety_message'],
                      raw_distance_cm=report.get('raw_distance_cm'))
        self.samples.append(sample)
        mode = 'CHECK' if self.check else 'DRIVE'
        print(f"{mode} {sample['seconds']:.1f}s wheels={sample['speeds']} step={sample['route_step']} "
              f"reason={sample['reason']} ultra={sample['raw_distance_cm']}cm lane={sample['lane_hz']:.1f}/s YOLO={sample['yolo_hz']:.1f}/s CPU={sample['cpu_c']}C",flush=True)
        self.last_time,self.last_lane,self.last_vision = now,report['runtime_lane_frames'],count

    def summary(self):
        if self.finished is None:self.finish()
        elapsed = self.finished-self.started
        lane_frames = 0 if self.report is None else self.report['runtime_lane_frames']
        yolo_frames = self.final_vision-self.first_vision
        return dict(seconds=elapsed,lane_frames=lane_frames,yolo_frames=yolo_frames,
                    lane_hz=lane_frames/elapsed,yolo_hz=yolo_frames/elapsed,
                    temperature_start_c=self.initial_temperature,temperature_end_c=self.final_temperature,
                    samples=self.samples,last_report=self.report)


def main(argv=None):
    parser = argparse.ArgumentParser(description='전체 코스 주행 / --check는 바퀴 명령 없이 같은 판단과 녹화')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--seconds',type=float,help='지정 초 뒤 종료(생략하면 키/완주/오류까지)')
    args = parser.parse_args(argv)
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds<=0):parser.error('--seconds는 양수여야 합니다')
    try:
        ready = input('카메라 앞을 가리지 않고 START 차선 가운데 바닥에 놓았으며 사방1m 바닥을 비웠나요? (y/n) ')
    except (EOFError,KeyboardInterrupt):
        ready = 'n'
    if ready.strip().lower() != 'y':
        print('중단했습니다. 서보·바퀴를 움직이지 않았습니다.')
        return 0
    stamp = datetime.now(lane.KST).strftime('%Y%m%d_%H%M%S_%f')
    root = Path(__file__).resolve().parents[1]/'results'
    root.mkdir(exist_ok=True)
    csv_path = root/f'full_course_{stamp}.csv'
    json_path = root/f'full_course_{stamp}.json'
    bot = motor = camera = vision = recorder = monitor = None
    reason = '준비 중'
    errors = []
    started = time.monotonic()
    try:
        from Raspbot_Lib import Raspbot
        bot = Raspbot()
        motor = MotorOutput(bot,args.check)
        if not args.check:motor(lane.STOP)
        pose = prepare_camera(bot)
        print(f"카메라 준비: 팬 {pose['pan']} · 틸트 {pose['tilt']} ({pose['source']})",flush=True)
        checked_driver_call(bot.Ctrl_Ulatist_Switch,1)
        time.sleep(1)
        camera = lane.video.LatestCamera().start()
        vision = FullCourseVisionWorker(camera).start()
        recorder = FullCourseRecorder(camera)
        monitor = RuntimeMonitor(vision,args.check)
        with obstacles.keyboard_stop() as keyboard:
            def finish_outputs():
                monitor.finish()
                motor.close()
            def stop_requested():
                nonlocal reason
                if keyboard():reason = '키 입력(q 포함)';return True
                if args.seconds is not None and time.monotonic()-monitor.started>=args.seconds:
                    reason = f'{args.seconds:g}초 경과';return True
                return False
            with csv_path.open('x',newline='',encoding='utf-8') as stream:
                report = run_safety_loop(camera,vision,lambda:obstacles.read_distance_cm(bot),
                    stop_requested,stream,motor,recorder=recorder,on_report=monitor.update,on_stop=finish_outputs)
            if reason=='준비 중':reason = report['state']
    except KeyboardInterrupt:reason = 'Ctrl+C'
    except Exception as exc:
        reason = f'오류: {exc}'
        errors.append(str(exc))
    finally:
        if monitor is not None:monitor.finish()
        if motor is not None:
            try:motor.close()
            except Exception as exc:errors.append(str(exc))
        for resource in (recorder,vision,camera):
            if resource is not None:
                try:resource.close()
                except Exception as exc:errors.append(str(exc))
        if bot is not None:
            try:checked_driver_call(bot.Ctrl_Ulatist_Switch,0)
            except Exception as exc:errors.append(str(exc))
        if errors and not reason.startswith('오류:'):reason += ' / 정리 오류'
        result = dict(check=args.check,reason=reason,errors=errors,total_seconds=time.monotonic()-started,
                      motor_commands=0 if motor is None else motor.commands,
                      motor_batches=0 if motor is None else motor.batches,
                      csv=str(csv_path),videos={} if recorder is None else {k:str(v) for k,v in recorder.paths.items()},
                      metrics=None if monitor is None else monitor.summary())
        json_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(f'종료: {reason}',flush=True)
        for name,path in dict(CSV=csv_path,JSON=json_path,**result['videos']).items():print(f'{name}: {path}',flush=True)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
