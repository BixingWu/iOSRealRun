"""Qt map route editor using the existing OpenStreetMap tile cache."""

import math
import queue
import time
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_routes import MAX_ROUTE_POINTS
from map_picker import (
    MAX_ZOOM,
    MIN_ZOOM,
    TILE_SIZE,
    _TileLoader,
    _fit,
    _parse_center,
    _project,
    _route_pixels,
    _unproject,
    _visible_tiles,
)


BLUE = "#0075e8"
BORDER = "#dce5f0"
MAP_BACKGROUND = "#eaf0f7"
MAX_IMAGE_TILES = 72
OSM_COPYRIGHT = QUrl("https://www.openstreetmap.org/copyright")

PICKER_STYLE = """
QDialog#routePicker { background: #f3f6fa; color: #172232; }
QLabel#mapHint { color: #526276; }
QLabel#mapSummary { color: #526276; }
QLabel#coordinateError { color: #a42931; }
QFrame#mapControls, QFrame#coordinateControls {
    background: #ffffff; border: 1px solid #dce5f0; border-radius: 14px;
}
QPushButton {
    color: #172232; background: #ffffff; border: 1px solid #dce5f0;
    border-radius: 10px; padding: 7px 14px; min-height: 18px;
}
QPushButton:hover { background: #eef5ff; border-color: #cddff3; }
QPushButton:pressed { background: #e0eeff; }
QPushButton:focus { border-color: #0075e8; }
QPushButton:disabled { color: #8994a5; background: #f1f4f8; border-color: #e3eaf2; }
QPushButton#mapApply {
    color: #ffffff; background: #0075e8; border-color: #0075e8; font-weight: 600;
}
QPushButton#mapApply:hover { background: #0867c4; }
QPushButton#mapApply:disabled { color: #78879b; background: #dce7f4; border-color: #dce7f4; }
QPushButton#zoomButton {
    padding: 0 8px; min-width: 25px; min-height: 26px; border-radius: 8px;
    font-size: 17px; font-weight: 500;
}
QPushButton#mapAttribution {
    color: #3b5876; padding: 3px 7px; min-height: 13px; border-radius: 6px; font-size: 11px;
}
QLineEdit {
    background: #ffffff; color: #172232; border: 1px solid #dce5f0; border-radius: 9px;
    padding: 7px 10px; min-height: 18px; selection-background-color: #afd4ff;
}
QLineEdit:focus { border-color: #0075e8; }
"""


class _MapCanvas(QWidget):
    changed = Signal()

    def __init__(self, parent, initial_points, closed, load_tiles):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("路线地图")
        self.setAccessibleDescription("点击添加点，拖动平移，滚轮缩放。也可用方向键和空格。")
        self.points = []
        self._closed_route = closed
        self._seed = list(initial_points)
        self._fit_pending = True
        self._zoom, self._x, self._y = _fit(self._seed, 860, 530)
        self._press = None
        self._dragging = False
        self._images = OrderedDict()
        self._unavailable = {}
        self._visible = []
        self._loader = _TileLoader() if load_tiles else None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._request)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(75)
        self._poll_timer.timeout.connect(self._poll)
        if self._loader:
            self._poll_timer.start()
            self.destroyed.connect(self._loader.close)

        zoom = QFrame(self)
        zoom.setObjectName("mapControls")
        layout = QVBoxLayout(zoom)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        for label, direction, name in (("+", 1, "放大"), ("−", -1, "缩小")):
            button = QPushButton(label, zoom)
            button.setObjectName("zoomButton")
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.setAutoDefault(False)
            button.clicked.connect(lambda checked=False, direction=direction: self.zoom(direction))
            layout.addWidget(button)
        self._zoom_widget = zoom
        self._attribution = QPushButton("© OpenStreetMap contributors", self)
        self._attribution.setObjectName("mapAttribution")
        self._attribution.setAutoDefault(False)
        self._attribution.clicked.connect(lambda: QDesktopServices.openUrl(OSM_COPYRIGHT))

    def stop(self):
        for timer in (self._debounce, self._retry_timer, self._poll_timer):
            timer.stop()
        if self._loader:
            self._loader.close()
            self._loader = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_pending and self.width() > 10 and self.height() > 10:
            self._zoom, self._x, self._y = _fit(self._seed, self.width(), self.height())
            self._seed.clear()
            self._fit_pending = False
        for control in (self._zoom_widget, self._attribution):
            control.adjustSize()
        self._zoom_widget.move(self.width() - self._zoom_widget.width() - 12, 12)
        self._attribution.move(self.width() - self._attribution.width() - 9,
                               self.height() - self._attribution.height() - 9)
        self._viewport_changed()

    def _viewport_changed(self):
        self._visible = _visible_tiles(self._zoom, self._x, self._y, self.width(), self.height())
        if self._loader:
            self._loader.request(())
            self._retry_timer.stop()
        self.update()
        self.changed.emit()
        if self._loader and not self._dragging:
            self._debounce.start()

    def _draft_changed(self):
        self.update()
        self.changed.emit()

    def _retry(self):
        if not self._debounce.isActive():
            self._request()

    def _request(self):
        if not self._loader or not self.isVisible() or self._dragging:
            return
        now = time.monotonic()
        self._unavailable = {key: until for key, until in self._unavailable.items() if until > now}
        keys = [key for key, _, _ in self._visible if key not in self._images and key not in self._unavailable]
        self._loader.request(keys)
        self._schedule_retry(now)
        self.changed.emit()

    def _schedule_retry(self, now):
        self._retry_timer.stop()
        retry = min((self._unavailable[key] for key, _, _ in self._visible if key in self._unavailable), default=None)
        if retry is not None:
            self._retry_timer.start(min(2_147_483_647, max(1, math.ceil((retry - now) * 1000))))

    def _poll(self):
        if not self._loader:
            return
        changed = False
        for _ in range(32):
            try:
                key, data = self._loader.results.get_nowait()
            except queue.Empty:
                break
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data, "PNG"):
                self._images[key] = pixmap
                self._images.move_to_end(key)
                self._unavailable.pop(key, None)
            else:
                self._unavailable[key] = time.monotonic() + max(30, self._loader.retry_delay)
            changed = True
        if not changed:
            return
        visible = {key for key, _, _ in self._visible}
        for key in tuple(self._images):
            if len(self._images) <= MAX_IMAGE_TILES:
                break
            if key not in visible:
                del self._images[key]
        self._schedule_retry(time.monotonic())
        self._draft_changed()

    def status(self):
        keys = {key for key, _, _ in self._visible}
        if not self._loader or not keys:
            return ""
        if keys & self._unavailable.keys():
            return "底图暂不可用" if keys <= self._unavailable.keys() else "部分底图暂不可用"
        if keys - self._images.keys():
            return "底图载入中"
        return ""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        outline = QPainterPath()
        outline.addRoundedRect(area, 14, 14)
        painter.setClipPath(outline)
        painter.fillRect(self.rect(), QColor(MAP_BACKGROUND))
        self._paint_tiles(painter)
        self._paint_route(painter)
        painter.setClipping(False)
        painter.setPen(QColor(BORDER))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)

    def _paint_tiles(self, painter):
        painter.setPen(QColor(BORDER))
        for key, x, y in self._visible:
            pixmap = self._images.get(key)
            if pixmap is None:
                painter.drawRect(x, y, TILE_SIZE, TILE_SIZE)
            else:
                painter.drawPixmap(x, y, pixmap)

    def _paint_route(self, painter):
        if not self.points:
            return
        size = TILE_SIZE * 2 ** self._zoom
        closing = self._closed_route and len(self.points) > 1 and self.points[0] != self.points[-1]
        route = self.points + self.points[:1] if closing else self.points
        positions = _route_pixels(route, self._zoom, self._x, self._y, self.width(), self.height())
        left = min(x for x, _ in positions)
        right = max(x for x, _ in positions)
        copies = range(math.ceil((-right - 8) / size), math.floor((self.width() - left + 8) / size) + 1)
        for copy in copies:
            self._paint_route_copy(painter, [QPointF(x + copy * size, y) for x, y in positions], closing)

    @staticmethod
    def _paint_route_copy(painter, positions, closing):
        path = QPolygonF(positions[:-1] if closing else positions)
        if len(path) >= 2:
            for color, weight in (("#ffffff", 7), (BLUE, 3.5)):
                pen = QPen(QColor(color), weight)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPolyline(path)
        if closing:
            painter.setPen(QPen(QColor("#ffffff"), 6))
            painter.drawLine(positions[-2], positions[-1])
            painter.setPen(QPen(QColor(BLUE), 2, Qt.PenStyle.DashLine))
            painter.drawLine(positions[-2], positions[-1])
        for index, point in enumerate(path):
            radius = 5.5 if index in (0, len(path) - 1) else 3.4
            painter.setPen(QPen(QColor(BLUE if index == 0 else "#ffffff"), 1.5))
            painter.setBrush(QColor("#ffffff" if index == 0 else BLUE))
            painter.drawEllipse(point, radius, radius)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        self._press = event.position(), self._x, self._y
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is None:
            return super().mouseMoveEvent(event)
        origin, x, y = self._press
        offset = origin - event.position()
        if self._dragging or math.hypot(offset.x(), offset.y()) >= 5:
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._set_center(x + offset.x(), y + offset.y())
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        self._press = None
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._viewport_changed()
        else:
            self.add_point(event.position())
        event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if self._press is None and delta:
            self.zoom(1 if delta > 0 else -1, event.position())
        event.accept()

    def keyPressEvent(self, event):
        directions = {
            Qt.Key.Key_Left: (-60, 0), Qt.Key.Key_Right: (60, 0),
            Qt.Key.Key_Up: (0, -60), Qt.Key.Key_Down: (0, 60),
        }
        if event.key() in directions:
            dx, dy = directions[event.key()]
            self._set_center(self._x + dx, self._y + dy)
        elif event.key() == Qt.Key.Key_Space:
            self.add_point(QPointF(self.width() / 2, self.height() / 2))
        elif event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom(-1 if event.key() == Qt.Key.Key_Minus else 1)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def _set_center(self, x, y):
        size = TILE_SIZE * 2 ** self._zoom
        self._x, self._y = x % size, max(0, min(size, y))
        self._viewport_changed()

    def zoom(self, direction, anchor=None):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom + direction))
        if zoom == self._zoom:
            return
        dx = anchor.x() - self.width() / 2 if anchor is not None else 0
        dy = anchor.y() - self.height() / 2 if anchor is not None else 0
        factor = 2 ** (zoom - self._zoom)
        self._zoom = zoom
        self._set_center((self._x + dx) * factor - dx, (self._y + dy) * factor - dy)

    def center_on(self, point):
        self._zoom = 16
        self._set_center(*_project(point, self._zoom))

    def add_point(self, point):
        if not QRectF(self.rect()).contains(point) or len(self.points) >= MAX_ROUTE_POINTS:
            return
        x = self._x + point.x() - self.width() / 2
        y = self._y + point.y() - self.height() / 2
        if not 0 <= y <= TILE_SIZE * 2 ** self._zoom:
            return
        position = {key: round(value, 7) for key, value in _unproject(x, y, self._zoom).items()}
        if not self.points or self.points[-1] != position:
            self.points.append(position)
            self._draft_changed()

    def undo(self):
        if self.points:
            self.points.pop()
            self._draft_changed()

    def clear(self):
        if self.points:
            self.points.clear()
            self._draft_changed()


class MapPicker(QDialog):
    def __init__(self, parent, initial_points, on_apply, closed=False, *, load_tiles=True):
        super().__init__(parent)
        self.setObjectName("routePicker")
        self.setWindowTitle("绘制路线")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(PICKER_STYLE)
        self._on_apply = on_apply
        self._stopped = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        hint = QLabel("点击选点，拖动平移 · 滚轮缩放", self)
        hint.setObjectName("mapHint")
        hint.setWordWrap(True)
        toolbar.addWidget(hint, 1)
        self.go_button = QPushButton("定位到…", self)
        self.go_button.setAutoDefault(False)
        self.go_button.clicked.connect(self._toggle_coordinates)
        toolbar.addWidget(self.go_button)
        layout.addLayout(toolbar)

        self.coordinate_panel = QFrame(self)
        self.coordinate_panel.setObjectName("coordinateControls")
        coord = QHBoxLayout(self.coordinate_panel)
        coord.setContentsMargins(10, 8, 10, 8)
        self.coordinate_input = QLineEdit(self.coordinate_panel)
        self.coordinate_input.setPlaceholderText("纬度, 经度 · 30.2675, 120.1203")
        self.coordinate_input.setAccessibleName("WGS 84 纬度和经度")
        self.coordinate_input.returnPressed.connect(self._go_to)
        coord.addWidget(self.coordinate_input, 1)
        go = QPushButton("定位", self.coordinate_panel)
        go.setAutoDefault(False)
        go.clicked.connect(self._go_to)
        coord.addWidget(go)
        self.coordinate_error = QLabel("请输入有效的纬度和经度", self.coordinate_panel)
        self.coordinate_error.setObjectName("coordinateError")
        self.coordinate_error.setVisible(False)
        coord.addWidget(self.coordinate_error)
        self.coordinate_panel.hide()
        layout.addWidget(self.coordinate_panel)

        self.canvas = _MapCanvas(self, initial_points, closed, load_tiles)
        layout.addWidget(self.canvas, 1)

        footer = QHBoxLayout()
        self.summary = QLabel(self)
        self.summary.setObjectName("mapSummary")
        self.summary.setWordWrap(True)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.summary, 1)
        self.undo_button = QPushButton("撤销", self)
        self.clear_button = QPushButton("清空", self)
        self.apply_button = QPushButton("使用路线", self)
        self.apply_button.setObjectName("mapApply")
        for button, slot in (
            (self.undo_button, self.canvas.undo), (self.clear_button, self.canvas.clear),
            (self.apply_button, self._apply),
        ):
            button.setAutoDefault(False)
            button.clicked.connect(slot)
            footer.addWidget(button)
        layout.addLayout(footer)

        undo = QShortcut(QKeySequence.StandardKey.Undo, self.canvas)
        undo.setContext(Qt.ShortcutContext.WidgetShortcut)
        undo.activated.connect(self.canvas.undo)
        self.canvas.changed.connect(self._refresh)
        self._refresh()
        screen = parent.screen() if parent is not None else self.screen()
        available = screen.availableGeometry()
        self.resize(min(870, max(400, available.width() - 50)), min(620, max(290, available.height() - 55)))
        self.canvas.setFocus()

    def _toggle_coordinates(self):
        if self.coordinate_panel.isVisible():
            self.coordinate_panel.hide()
            self.canvas.setFocus()
        else:
            self.coordinate_error.hide()
            self.coordinate_panel.show()
            self.coordinate_input.setFocus()
            self.coordinate_input.selectAll()

    def _go_to(self):
        try:
            point = _parse_center(self.coordinate_input.text())
        except ValueError:
            self.coordinate_error.show()
            self.coordinate_input.setFocus()
            return
        self.coordinate_panel.hide()
        self.canvas.center_on(point)
        self.canvas.setFocus()

    def _refresh(self):
        count = len(self.canvas.points)
        self.undo_button.setEnabled(count > 0)
        self.clear_button.setEnabled(count > 0)
        self.apply_button.setEnabled(count >= 2)
        parts = ["至少选择两个点"] if count < 2 else []
        state = self.canvas.status()
        if state:
            parts.append(state)
        self.summary.setText(" · ".join(parts))

    def _apply(self):
        if self._stopped or len(self.canvas.points) < 2:
            return
        points = self.canvas.points.copy()
        self.accept()
        self._on_apply(points)

    def done(self, result):
        if not self._stopped:
            self._stopped = True
            self.canvas.stop()
        super().done(result)


def open_map_picker(parent, initial_points, on_apply, *, closed=False, load_tiles=True):
    """Open an empty draft fitted to the current route and return the dialog."""
    dialog = MapPicker(parent, initial_points, on_apply, closed, load_tiles=load_tiles)
    dialog.open()
    return dialog
