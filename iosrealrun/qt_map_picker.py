"""Shared map canvas for drafting routes and watching a replay."""

import math
import queue
import time
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
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

from iosrealrun.desktop_routes import MAX_ROUTE_POINTS
from iosrealrun.qt_controls import CheckBox, ComboBox
from iosrealrun.route_drawing import SHAPES, shape_route, smooth_route
from iosrealrun.map_picker import (
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


BLUE = "#0874e8"
BORDER = "#dce5f2"
MAP_BACKGROUND = "#f3f7fc"
MAX_IMAGE_TILES = 72
DEFAULT_STYLE = "city"
MAP_STYLES = {"city": "城市街图", "light": "清爽", "street": "街道", "dark": "夜色",
              "osm": "经典街图", "plain": "纯轨迹"}
OSM_CREDIT = '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>'
VECTOR_CREDIT = ('<a href="https://openfreemap.org/">OpenFreeMap</a> · '
                 '<a href="https://openmaptiles.org/">© OpenMapTiles</a> · ' + OSM_CREDIT)

PICKER_STYLE = """
QDialog#routePicker { background: #f3f7fc; color: #192c47; }
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
    color: #ffffff; background: #0874e8; border-color: #0874e8; font-weight: 600;
}
QPushButton#mapApply:hover { background: #0564cb; }
QPushButton#mapApply:disabled { color: #78879b; background: #dce7f4; border-color: #dce7f4; }
QPushButton#zoomButton {
    padding: 0 8px; min-width: 25px; min-height: 26px; border-radius: 8px;
    font-size: 17px; font-weight: 500;
}
QLineEdit {
    background: #ffffff; color: #172232; border: 1px solid #dce5f0; border-radius: 9px;
    padding: 7px 10px; min-height: 18px; selection-background-color: #afd4ff;
}
QLineEdit:focus { border-color: #0075e8; }
QComboBox { background: #f5f8fc; border: 1px solid #dce5f0; border-radius: 9px;
            min-height: 32px; padding: 0 25px 0 10px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow { image: none; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #c5d3e5; border-radius: 5px; }
QCheckBox::indicator:checked { background: #0874e8; border-color: #0874e8; }
"""


class _MapCanvas(QWidget):
    changed = Signal()

    def __init__(self, parent, initial_points, closed, load_tiles, *, editable=True, style=DEFAULT_STYLE):
        super().__init__(parent)
        self.setMinimumHeight(190 if editable else 105)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._editable = editable
        self._auto_fit = not editable
        self._idle_cursor = Qt.CursorShape.CrossCursor if editable else Qt.CursorShape.OpenHandCursor
        self.setCursor(self._idle_cursor)
        self.setAccessibleName("路线地图")
        self.setAccessibleDescription("点击添加点，拖动平移，滚轮缩放。也可用方向键和空格。"
                                      if editable else "拖动平移，滚轮缩放。地图显示路线和当前模拟位置。")
        self.points = []
        self.shape = None
        self.corners = []
        self.smoothing = True
        self.draft_route = []
        self.marker = None
        self._geometry = None
        self._closed_route = closed
        self._seed = list(initial_points)
        self.reference = self._seed.copy() if editable else []
        self.show_reference = bool(self.reference)
        self._guide_geometry = None
        self._fit_pending = True
        self._zoom, self._x, self._y = _fit(self._seed, 860, 530)
        self._press = None
        self._dragging = False
        self._images = OrderedDict()
        self._unavailable = {}
        self._visible = []
        self.map_style = None
        self._load_tiles = load_tiles
        self._loader = None

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
        self._attribution = QLabel(self)
        self._attribution.setOpenExternalLinks(True)
        self._attribution.setTextFormat(Qt.TextFormat.RichText)
        self._attribution.setStyleSheet("background: rgba(255,255,255,235); border-radius: 4px;"
                                        "padding: 2px 5px; color: #355577; font-size: 10px;")
        self.set_map_style(style)

    def set_map_style(self, style):
        if style not in MAP_STYLES:
            raise ValueError(f"Unknown map style: {style}")
        if self.map_style == style:
            return
        self.stop()
        self.map_style = style
        self._images.clear()
        self._unavailable.clear()
        if self._load_tiles and style != "plain":
            if style == "osm":
                self._loader = _TileLoader()
            else:
                from iosrealrun.vector_tiles import _VectorTileLoader
                self._loader = _VectorTileLoader(style)
            self._poll_timer.start()
            self.destroyed.connect(self._loader.close)
        text = OSM_CREDIT if style == "osm" else VECTOR_CREDIT
        self._attribution.setText(text.replace('<a href=', '<a style="color:#315776" href='))
        self._attribution.setVisible(style != "plain")
        self._place_controls()
        self._viewport_changed()

    def stop(self):
        for timer in (self._debounce, self._retry_timer, self._poll_timer):
            timer.stop()
        if self._loader:
            self.destroyed.disconnect(self._loader.close)
            self._loader.close()
            self._loader = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_pending and self.width() > 10 and self.height() > 10:
            self._frame(self._seed)
            self._seed.clear()
            self._fit_pending = False
        elif not self._editable and self._auto_fit:
            self._frame(self.points)
        self._place_controls()
        self._viewport_changed()

    def _place_controls(self):
        for control in (self._zoom_widget, self._attribution):
            control.adjustSize()
        self._zoom_widget.move(self.width() - self._zoom_widget.width() - 12, 12)
        self._attribution.move(self.width() - self._attribution.width() - 9,
                               self.height() - self._attribution.height() - 9)

    def _frame(self, points):
        # _fit reserves 72 px on each edge. Use a smaller inset on compact screens.
        inset = min(48, min(self.width(), self.height()) // 6)
        allowance = 144 - 2 * inset
        self._zoom, self._x, self._y = _fit(points, self.width() + allowance, self.height() + allowance)

    def _viewport_changed(self):
        self._geometry = None
        self._guide_geometry = None
        self._visible = _visible_tiles(self._zoom, self._x, self._y, self.width(), self.height())
        if self._loader:
            self._loader.request(())
            self._retry_timer.stop()
        self.update()
        self.changed.emit()
        if self._loader and not self._dragging:
            self._debounce.start()

    def _draft_changed(self):
        if self.shape:
            self.draft_route = shape_route(self.shape, self.corners)
        elif self.smoothing:
            self.draft_route = smooth_route(self.points, closed=self._closed_route)
        else:
            self.draft_route = self.points.copy()
        self._geometry = None
        self.update()
        self.changed.emit()

    @property
    def controls(self):
        return self.corners if self.shape else self.points

    @property
    def route_closed(self):
        return self.shape != "ikun" if self.shape else self._closed_route

    def select_shape(self, shape):
        self.shape = shape
        self._draft_changed()

    def set_smoothing(self, enabled):
        self.smoothing = enabled
        self._draft_changed()

    def set_reference_visible(self, enabled):
        self.show_reference = enabled
        self.update()

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
        self.update()
        self.changed.emit()

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
        painter.fillRect(self.rect(), QColor("#243235" if self.map_style == "dark" else MAP_BACKGROUND))
        self._paint_tiles(painter)
        if self._editable:
            self._paint_guides(painter)
        self._paint_route(painter)
        painter.setClipping(False)
        painter.setPen(QColor(BORDER))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)

    def _paint_tiles(self, painter):
        painter.setPen(QColor("#34454a" if self.map_style == "dark" else "#e3ebf5"))
        for key, x, y in self._visible:
            pixmap = self._images.get(key)
            if pixmap is None:
                painter.drawRect(x, y, TILE_SIZE, TILE_SIZE)
            else:
                painter.drawPixmap(x, y, pixmap)

    def _screen_path(self, points):
        return QPolygonF([QPointF(x, y) for x, y in
                          _route_pixels(points, self._zoom, self._x, self._y, self.width(), self.height())])

    def _paint_guides(self, painter):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.show_reference and self.reference:
            if self._guide_geometry is None:
                self._guide_geometry = self._screen_path(self.reference)
            pen = QPen(QColor("#6681a0"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolyline(self._guide_geometry)
        if self.shape and self.corners:
            corners = self._screen_path(self.corners)
            painter.setPen(QPen(QColor("#4d77ab"), 1.2, Qt.PenStyle.DashLine))
            if len(corners) == 2:
                painter.drawRect(QRectF(corners.first(), corners.last()).normalized())
            painter.setBrush(QColor("#ffffff"))
            for corner in corners:
                painter.drawRect(QRectF(corner.x() - 3, corner.y() - 3, 6, 6))

    def _paint_route(self, painter):
        points = self.draft_route if self._editable else self.points
        if not points:
            return
        size = TILE_SIZE * 2 ** self._zoom
        if self._geometry is None:
            closing = self.route_closed and len(points) > 1 and points[0] != points[-1]
            route = points + points[:1] if closing else points
            positions = self._screen_path(route)
            path = QPolygonF(positions)
            if closing:
                path.removeLast()
            last = positions[-1] if closing else None
            anchors = self._screen_path(self.points) if self._editable and not self.shape else None
            bounds = positions.boundingRect()
            self._geometry = (path, last, anchors, bounds.left(), bounds.right())
        path, closing_point, anchors, left, right = self._geometry
        copies = range(math.ceil((-right - 8) / size), math.floor((self.width() - left + 8) / size) + 1)
        for copy in copies:
            painter.save()
            painter.translate(copy * size, 0)
            self._paint_route_copy(painter, path, closing_point, anchors)
            painter.restore()
        if self.marker is not None:
            x, y = _route_pixels([self.marker], self._zoom, self._x, self._y, self.width(), self.height())[0]
            for copy in range(math.ceil((-x - 13) / size), math.floor((self.width() - x + 13) / size) + 1):
                mark = QPointF(x + copy * size, y)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(235, 147, 30, 65))
                painter.drawEllipse(mark, 13, 13)
                painter.setPen(QPen(QColor("#513a23"), 4))
                painter.setBrush(QColor("#ef9c28"))
                painter.drawEllipse(mark, 7, 7)
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.drawEllipse(mark, 7, 7)

    def _paint_route_copy(self, painter, path, closing_point, anchors):
        if len(path) >= 2:
            for color, weight in (("#ffffff", 7), (BLUE, 3.5)):
                pen = QPen(QColor(color), weight)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPolyline(path)
        if closing_point is not None:
            painter.setPen(QPen(QColor("#ffffff"), 6))
            painter.drawLine(path.last(), closing_point)
            painter.setPen(QPen(QColor(BLUE), 2, Qt.PenStyle.DashLine))
            painter.drawLine(path.last(), closing_point)
        if anchors is not None:
            markers = anchors
        else:
            markers = [path.first()] if self.route_closed else [path.first(), path.last()]
        for index, point in enumerate(markers):
            radius = 5.5 if index in (0, len(markers) - 1) else 3.4
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
            self.setCursor(self._idle_cursor)
            self._viewport_changed()
        elif self._editable:
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
        elif event.key() == Qt.Key.Key_Space and self._editable:
            self.add_point(QPointF(self.width() / 2, self.height() / 2))
        elif event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom(-1 if event.key() == Qt.Key.Key_Minus else 1)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def _set_center(self, x, y):
        self._auto_fit = False
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
        if not self._editable or not QRectF(self.rect()).contains(point):
            return
        x = self._x + point.x() - self.width() / 2
        y = self._y + point.y() - self.height() / 2
        if not 0 <= y <= TILE_SIZE * 2 ** self._zoom:
            return
        position = {key: round(value, 7) for key, value in _unproject(x, y, self._zoom).items()}
        controls = self.controls
        if controls and controls[-1] == position:
            return
        if self.shape and len(controls) == 2:
            controls[-1] = position
        elif len(controls) < MAX_ROUTE_POINTS:
            controls.append(position)
        else:
            return
        self._draft_changed()

    def undo(self):
        if self.controls:
            self.controls.pop()
            self._draft_changed()

    def clear(self):
        if self.controls:
            self.controls.clear()
            self._draft_changed()


class MapPreview(_MapCanvas):
    """Read-only map. Replays move the marker without changing the viewport."""

    def __init__(self, parent=None, *, load_tiles=True, style=DEFAULT_STYLE):
        super().__init__(parent, (), False, load_tiles, editable=False, style=style)

    def set_route(self, points, closed):
        self.points = list(points)
        self._closed_route = closed
        self.marker = None
        self.fit_route()

    def fit_route(self):
        self._auto_fit = True
        self._fit_pending = False
        self._frame(self.points)
        self._viewport_changed()

    def set_marker(self, point):
        self.marker = point
        self.update()


class MapPicker(QDialog):
    mapStyleChanged = Signal(str)

    def __init__(self, parent, initial_points, on_apply, closed=False, *, load_tiles=True, style=DEFAULT_STYLE):
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
        self.hint = QLabel(self)
        self.hint.setObjectName("mapHint")
        self.hint.setWordWrap(True)
        toolbar.addWidget(self.hint, 1)
        self.style_box = ComboBox(self)
        self.style_box.setAccessibleName("地图样式")
        self.style_box.setToolTip("地图样式")
        for style_id, name in MAP_STYLES.items():
            self.style_box.addItem(name, style_id)
        self.style_box.setCurrentIndex(self.style_box.findData(style))
        toolbar.addWidget(self.style_box)
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

        self.canvas = _MapCanvas(self, initial_points, closed, load_tiles, style=style)
        tools = QHBoxLayout()
        self.shape_box = ComboBox(self)
        self.shape_box.setAccessibleName("绘制方式")
        self.shape_box.addItem("手绘选点", "")
        for kind, name in SHAPES.items():
            self.shape_box.addItem(name, kind)
        self.shape_box.currentIndexChanged.connect(lambda: self.canvas.select_shape(self.shape_box.currentData()))
        tools.addWidget(self.shape_box)
        self.smooth_box = CheckBox("平滑补点", self)
        self.smooth_box.setToolTip("从第三个手绘点开始圆滑转弯，沿曲线约每 3 米补一个点")
        self.smooth_box.setChecked(True)
        self.smooth_box.toggled.connect(self.canvas.set_smoothing)
        tools.addWidget(self.smooth_box)
        self.reference_box = CheckBox("显示参考路线", self)
        self.reference_box.setToolTip("用灰蓝色虚线显示打开绘图前的路线")
        self.reference_box.setChecked(self.canvas.show_reference)
        self.reference_box.setEnabled(bool(self.canvas.reference))
        self.reference_box.toggled.connect(self.canvas.set_reference_visible)
        tools.addWidget(self.reference_box)
        tools.addStretch()
        layout.addLayout(tools)
        self.style_box.currentIndexChanged.connect(self._select_style)
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

    def _select_style(self, index):
        style = self.style_box.itemData(index)
        self.canvas.set_map_style(style)
        self.mapStyleChanged.emit(style)

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
        count = len(self.canvas.controls)
        output_count = len(self.canvas.draft_route)
        self.undo_button.setEnabled(count > 0)
        self.clear_button.setEnabled(count > 0)
        self.apply_button.setEnabled(output_count >= 2)
        shape = self.canvas.shape
        self.smooth_box.setVisible(not shape)
        if shape:
            self.hint.setText("在操场内点选区域的两个对角，可再次点选调整第二个角")
            parts = ["选第一个角" if not count else "选对角"] if count < 2 else [
                f"{SHAPES[shape]} · {output_count} 个路线点" if output_count else "请拉开两个角的距离"]
        else:
            self.hint.setText("点击选点，拖动平移，滚轮缩放")
            if self.canvas.smoothing and count >= 3:
                parts = [f"{count} 个手绘点 → {output_count} 个路线点"]
            else:
                parts = ["至少选择两个点"] if count < 2 else [f"已选 {count} 个点"]
        state = self.canvas.status()
        if state:
            parts.append(state)
        self.summary.setText(" · ".join(parts))

    def _apply(self):
        if self._stopped or len(self.canvas.draft_route) < 2:
            return
        points = self.canvas.draft_route.copy()
        self.accept()
        self._on_apply(points)

    def done(self, result):
        if not self._stopped:
            self._stopped = True
            self.canvas.stop()
        super().done(result)


def open_map_picker(parent, initial_points, on_apply, *, closed=False, load_tiles=True, style=DEFAULT_STYLE):
    """Open an empty draft fitted to the current route and return the dialog."""
    dialog = MapPicker(parent, initial_points, on_apply, closed, load_tiles=load_tiles, style=style)
    dialog.open()
    return dialog
