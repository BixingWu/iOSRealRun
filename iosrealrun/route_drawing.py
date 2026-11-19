"""Geometry for a hand-drawn route and single-stroke templates on the map."""

import math
from itertools import pairwise

from iosrealrun.desktop_routes import MAX_ROUTE_POINTS
from iosrealrun.map_picker import TILE_SIZE, _project, _unproject, _wrapped_delta


SHAPES = {"ikun": "连笔 IKUN", "heart": "爱心", "eight": "无限符号 ∞", "oval": "椭圆"}
POINT_SPACING_M = 3
EARTH_CIRCUMFERENCE = 2 * math.pi * 6_371_008.8


def _project_line(points):
    projected = []
    for point in points:
        x, y = _project(point, 0)
        if projected:
            previous_x = projected[-1][0]
            x = previous_x + _wrapped_delta(x, previous_x, TILE_SIZE)
        if not projected or (x, y) != projected[-1]:
            projected.append((x, y))
    return projected


def _metres_per_unit(points):
    latitude = sum(point["lat"] for point in points) / len(points)
    return EARTH_CIRCUMFERENCE * math.cos(math.radians(latitude)) / TILE_SIZE


def _mix(first, last, fraction):
    return (first[0] + (last[0] - first[0]) * fraction,
            first[1] + (last[1] - first[1]) * fraction)


def _round_corners(points, radius, closed):
    """Trim both sides of a turn and join them with a tangent quadratic Bézier."""
    vertices = [] if closed else [points[0]]
    indices = range(len(points)) if closed else range(1, len(points) - 1)
    for index in indices:
        before, corner, after = points[index - 1], points[index], points[(index + 1) % len(points)]
        incoming, outgoing = math.dist(before, corner), math.dist(corner, after)
        trim = min(radius, .28 * incoming, .28 * outgoing)
        if trim == 0:
            vertices.append(corner)
            continue
        entry = _mix(corner, before, trim / incoming)
        leave = _mix(corner, after, trim / outgoing)
        vertices.append(entry)
        for step in range(1, 9):
            t = step / 8
            vertices.append(_mix(_mix(entry, corner, t), _mix(corner, leave, t), t))
    vertices.append(vertices[0] if closed else points[-1])
    return vertices


def _sample(vertices, metres_per_unit, *, closed=False, minimum=1):
    """Sample by cumulative distance with bounded output, independent of map zoom."""
    lengths = [math.dist(a, b) for a, b in pairwise(vertices)]
    total = sum(lengths)
    if total <= 0:
        return []
    intervals = min(MAX_ROUTE_POINTS - 1, max(minimum, math.ceil(total * metres_per_unit / POINT_SPACING_M)))
    segment = 0
    offset = 0.0
    result = []
    for i in range(intervals):
        distance = total * (i / intervals)
        while segment < len(lengths) - 1 and offset + lengths[segment] <= distance:
            offset += lengths[segment]
            segment += 1
        t = (distance - offset) / lengths[segment] if lengths[segment] else 0
        xy = _mix(vertices[segment], vertices[segment + 1], t)
        result.append(_unproject(*xy, 0))
    if not closed:
        result.append(_unproject(*vertices[-1], 0))
    return result


def smooth_route(points, *, closed=False):
    if len(points) < 3:
        return list(points)
    xy = _project_line(points)
    if closed and len(xy) > 1 and xy[0] == xy[-1]:
        xy.pop()
    if len(xy) < 3:
        return list(points)
    scale = _metres_per_unit(points)
    rounded = _round_corners(xy, 12 / scale, closed)
    result = _sample(rounded, scale, closed=closed, minimum=len(xy) if closed else len(xy) - 1)
    if not closed:
        result[0], result[-1] = points[0], points[-1]
    return result


# A continuous pen stroke in letter-space. Travel between letters follows the baseline.
IKUN_STROKE = (
    (0, .16), (.27, .07), (.68, .07), (.47, .12), (.28, .90), (.02, .93),
    (.16, .84), (.52, .89), (.75, .86),
    (.99, .04), (.78, .91), (.90, .50), (1.57, .06), (.93, .50),
    (1.36, .89), (1.55, .84),
    (1.83, .06), (1.66, .62), (1.66, .78), (1.74, .89), (1.88, .91),
    (2.06, .79), (2.20, .56), (2.42, .06), (2.23, .79), (2.27, .90), (2.45, .83),
    (2.70, .06), (2.75, .05), (3.12, .87), (3.16, .88), (3.40, .05), (3.49, .02),
)


def _template(kind):
    if kind == "ikun":
        return _round_corners(IKUN_STROKE, .035, False)
    vertices = []
    for i in range(96):
        t = math.tau * i / 96
        if kind == "heart":
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t))
        elif kind == "eight":
            x, y = 2 * math.sin(t), math.sin(2*t)
        else:
            x, y = math.cos(t), math.sin(t)
        vertices.append((x, y))
    return vertices + vertices[:1]


def shape_route(kind, corners):
    """Fit a single stroke inside the two selected map corners, leaving a small margin."""
    if kind not in SHAPES or len(corners) != 2:
        return []
    box = _project_line(corners)
    if len(box) != 2:
        return []
    (x0, y0), (x1, y1) = box
    width, height = abs(x1 - x0), abs(y1 - y0)
    scale = _metres_per_unit(corners)
    if min(width, height) * scale < 1:
        return []
    vertices = _template(kind)
    if height > width and kind in ("ikun", "eight"):
        vertices = [(-y, x) for x, y in vertices]
    xs, ys = zip(*vertices)
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    sx, sy = .92 * width / (right - left), .92 * height / (bottom - top)
    if kind in ("ikun", "heart"):
        sx = sy = min(sx, sy)
    xy = [((x0 + x1) / 2 + (x - (left + right) / 2) * sx,
           (y0 + y1) / 2 + (y - (top + bottom) / 2) * sy) for x, y in vertices]
    return _sample(xy, scale, closed=kind != "ikun", minimum=96)
