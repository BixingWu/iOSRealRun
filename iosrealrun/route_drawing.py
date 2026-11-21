"""Geometry for a hand-drawn route and single-stroke templates on the map."""

import math
from itertools import pairwise

from iosrealrun.desktop_routes import MAX_ROUTE_POINTS
from iosrealrun.map_picker import TILE_SIZE, _project, _unproject, _wrapped_delta


SHAPES = {
    "ikun": "连笔 IKUN", "gem": "G.E.M.（解解）",
    "heart": "爱心", "eight": "无限符号 ∞", "oval": "椭圆",
}
# Keep retired geometry available when reopening a draft from its saved placement handles.
DRAFT_SHAPES = {*SHAPES, "notes"}
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


def track_angle(points):
    """Principal axis of a lap, in map radians (east = 0, south = π/2)."""
    projected = _project_line(points)
    if len(projected) < 3:
        return None
    origin_x, origin_y = projected[0]
    local = [(x - origin_x, y - origin_y) for x, y in projected]
    gap = math.dist(local[0], local[-1])
    if gap:
        local.append(local[0])
    length = area_twice = 0.0
    first_x = first_y = second_x = second_y = cross = 0.0
    for (x0, y0), (x1, y1) in pairwise(local):
        dx, dy = x1 - x0, y1 - y0
        span = math.hypot(dx, dy)
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        length += span
        area_twice += x0 * y1 - x1 * y0
        first_x += span * x
        first_y += span * y
        # Integrate the full segment so extra points on one straight don't skew the axis.
        second_x += span * (x * x + dx * dx / 12)
        second_y += span * (y * y + dy * dy / 12)
        cross += span * (x * y + dx * dy / 12)
    # Accept sampled laps that stop just short of their start; ignore open lines.
    if gap > .10 * length or abs(area_twice) <= 1e-9 * length * length:
        return None
    xx = second_x - first_x * first_x / length
    yy = second_y - first_y * first_y / length
    xy = cross - first_x * first_y / length
    if math.hypot(xx - yy, 2 * xy) <= .10 * (xx + yy):
        return None  # Near-circular outlines have no distinct long axis.
    angle = math.atan2(2 * xy, xx - yy) / 2
    # Read left to right on a horizontal track and top to bottom on a vertical one.
    return angle + math.pi if angle < -math.pi / 4 else angle


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

# Retrace the bars of G and E and loop the pen at the baseline for each full stop.
GEM_STROKE = (
    (.87, .25), (.78, .13), (.61, .06), (.42, .06), (.24, .13), (.11, .27),
    (.05, .46), (.05, .63), (.11, .78), (.24, .89), (.42, .94), (.62, .93),
    (.78, .85), (.86, .76), (.89, .53), (.55, .53), (.89, .53), (.86, .76), (.84, .93),
    (1.03, .93), (1.09, .88), (1.06, .81), (.99, .83), (.98, .89), (1.03, .93),
    (1.25, .93), (1.38, .07), (2.03, .07), (1.38, .07), (1.32, .47),
    (1.86, .47), (1.32, .47), (1.25, .93), (1.99, .93),
    (2.14, .93), (2.20, .88), (2.17, .81), (2.10, .83), (2.09, .89), (2.14, .93),
    (2.36, .93), (2.49, .07), (2.84, .65), (3.36, .07), (3.23, .93),
    (3.44, .93), (3.50, .88), (3.47, .81), (3.40, .83), (3.39, .89), (3.44, .93),
)
LETTERING_STROKES = {"ikun": IKUN_STROKE, "gem": GEM_STROKE}

# Follow the outside of both noteheads, their stems and their shared beam in one lap.
BEAMED_NOTES_OUTLINE = (
    (.32, .23), (1.19, .04), (1.19, .68), (1.17, .75), (1.09, .82), (.98, .85),
    (.89, .84), (.83, .80), (.82, .74), (.86, .69), (.93, .65), (1.02, .62),
    (1.09, .62), (1.09, .24), (.42, .39), (.42, .85), (.39, .93), (.31, .99),
    (.20, 1.02), (.10, 1.01), (.05, .97), (.04, .91), (.08, .85), (.16, .80),
    (.24, .77), (.32, .77),
)


def _template(kind):
    if kind in LETTERING_STROKES:
        return _round_corners(LETTERING_STROKES[kind], .035, False)
    if kind == "notes":
        return _round_corners(BEAMED_NOTES_OUTLINE, .035, True)
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


def shape_layout(kind, corners, *, lettering_direction="auto", field_angle=None, rotation=0.0):
    """Return the fitted stroke and its four-corner map outline for drawing the guide."""
    if kind not in DRAFT_SHAPES or len(corners) != 2:
        return [], []
    box = _project_line(corners)
    if len(box) != 2:
        return [], []
    (x0, y0), (x1, y1) = box
    lettering = kind in LETTERING_STROKES
    aligned = lettering and lettering_direction == "auto" and field_angle is not None
    angle = (field_angle if aligned else 0.0) + rotation
    ux, uy = math.cos(angle), math.sin(angle)
    dx, dy = x1 - x0, y1 - y0
    width, height = abs(dx * ux + dy * uy), abs(dy * ux - dx * uy)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def place(x, y):
        return cx + (x * ux - y * uy), cy + (x * uy + y * ux)

    outline = [_unproject(*place(i * width / 2, j * height / 2), 0)
               for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    scale = _metres_per_unit(corners)
    if min(width, height) * scale < 1:
        return [], outline
    vertices = _template(kind)
    upright = height > width and not aligned
    if lettering and lettering_direction != "auto":
        upright = lettering_direction == "vertical"
    if upright and (lettering or kind == "eight"):
        vertices = [(-y, x) for x, y in vertices]
    xs, ys = zip(*vertices)
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    sx, sy = .92 * width / (right - left), .92 * height / (bottom - top)
    if lettering:
        # Use both dimensions of the selected box. Limit distortion in very thin boxes.
        sx = .97 * width / (right - left)
        sy = .97 * height / (bottom - top)
        sx, sy = min(sx, 3.5 * sy), min(sy, 3.5 * sx)
    elif kind in ("heart", "notes"):
        sx = sy = min(sx, sy)
    xy = [place((x - (left + right) / 2) * sx, (y - (top + bottom) / 2) * sy)
          for x, y in vertices]
    return _sample(xy, scale, closed=not lettering, minimum=96), outline


def shape_route(kind, corners, *, lettering_direction="auto", field_angle=None, rotation=0.0):
    route, _ = shape_layout(kind, corners, lettering_direction=lettering_direction, field_angle=field_angle,
                            rotation=rotation)
    return route
