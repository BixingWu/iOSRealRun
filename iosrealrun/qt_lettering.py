"""Draw a closed lettering animation in the coordinate system of a Qt map canvas."""

import math
from typing import NamedTuple

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QTransform

from iosrealrun.route_drawing import LETTERING_STROKES, vertical_lettering


def _tangent(a, b, length):
    delta = b - a
    span = math.hypot(delta.x(), delta.y())
    return delta * (length / span) if span else QPointF()


class LetteringLap(NamedTuple):
    kind: str
    angle: float | None

    @classmethod
    def from_frame(cls, kind, frame, direction, follows_track):
        if kind not in LETTERING_STROKES or len(frame) != 4:
            return None
        across, down = frame[1] - frame[0], frame[2] - frame[1]
        width, height = math.hypot(*across.toTuple()), math.hypot(*down.toTuple())
        axis = down if vertical_lettering(direction, follows_track, width, height) else across
        return cls(kind, math.atan2(axis.y(), axis.x()))

    @classmethod
    def from_saved(cls, data):
        if not isinstance(data, (list, tuple)) or len(data) != 2:
            return None
        kind, angle = data
        if not isinstance(kind, str) or kind not in LETTERING_STROKES:
            return None
        if angle is not None and (type(angle) not in (float, int) or not -math.tau <= angle <= math.tau):
            return None
        return cls(kind, angle)

    def screen_path(self, stroke):
        """Fit the ink and a fixed return flourish together inside the lettering bounds."""
        if len(stroke) < 3:
            return QPainterPath()
        angle = self.angle
        if angle is None:
            # Older saved routes record their points but omit the reading direction.
            chord = stroke.last() - stroke.first()
            first, last = LETTERING_STROKES[self.kind][0], LETTERING_STROKES[self.kind][-1]
            angle = math.atan2(chord.y(), chord.x()) - math.atan2(last[1] - first[1], last[0] - first[0])
        flat = QTransform().rotateRadians(-angle).map(stroke)
        box = flat.boundingRect()
        if box.width() < 1e-9 or box.height() < 1e-9:
            return QPainterPath()
        model = QTransform().scale(3.5 / box.width(), 1 / box.height()).translate(-box.left(), -box.top()).map(flat)
        ink = QPainterPath()
        ink.addPolygon(model)
        start, end = model.first(), model.last()
        leave = end + _tangent(model[-2], end, .18)
        enter = start - _tangent(start, model[1], .18)
        if self.kind == "ikun":
            ink.cubicTo(leave, QPointF(3.82, -.10), QPointF(3.80, .35))
            ink.cubicTo(3.78, .80, 3.63, 1.13, 3.39, 1.20)
            ink.cubicTo(3.18, 1.27, 3.20, 1.01, 3.41, 1.06)
            ink.cubicTo(3.78, 1.16, 3.35, 1.42, 2.77, 1.33)
            ink.cubicTo(1.73, 1.20, .52, 1.36, .09, 1.18)
            ink.cubicTo(QPointF(-.40, .96), enter, start)
        else:
            ink.cubicTo(leave, QPointF(3.87, 1.14), QPointF(3.77, .84))
            ink.cubicTo(3.72, .69, 3.47, .74, 3.57, .93)
            ink.cubicTo(3.76, 1.29, 3.35, 1.35, 2.90, 1.30)
            ink.cubicTo(1.78, 1.18, .67, 1.42, .12, 1.18)
            ink.cubicTo(-.34, .98, -.33, .31, -.02, .03)
            ink.cubicTo(.20, -.18, .69, -.22, .90, -.09)
            ink.cubicTo(QPointF(1.15, .06), enter, start)
        ink.closeSubpath()
        extent = ink.boundingRect()
        fit = QTransform().rotateRadians(angle).translate(box.left(), box.top())
        fit.scale(box.width() / extent.width(), box.height() / extent.height())
        fit.translate(-extent.left(), -extent.top())
        return fit.map(ink)
