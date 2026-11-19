"""The graphical iOSRealRun application."""

import argparse
import asyncio
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QKeySequence, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from iosrealrun.app_version import VERSION
from iosrealrun.config import DEFAULT_LAPS, DEFAULT_SPEED, read_settings
from iosrealrun.desktop_device import connect_device, list_devices, replay_route, reset_location, reveal_developer_mode
from iosrealrun.desktop_routes import (
    MAX_ROUTE_BYTES, last_route_path, load_route, parse_route_text, read_last_route, route_length, save_last_route,
)
from iosrealrun.paths import BUNDLED_ROUTES as ROUTES, bundled_route, resolve_route
from iosrealrun.qt_controls import CheckBox, ComboBox
from iosrealrun.qt_map_picker import DEFAULT_STYLE, MAP_STYLES, MapPreview, open_map_picker
from iosrealrun.route_drawing import SHAPES
from iosrealrun.venue_reference import VenueComparison
from iosrealrun.run import to_wgs84


SYSTEMS = {"WGS 84 · GPS": "wgs84", "GCJ-02 · 高德 / 腾讯": "gcj02", "BD-09 · 百度": "bd09"}
BLUE = "#0874e8"
FONT_FAMILIES = {
    "win32": ["Microsoft YaHei UI", "Microsoft YaHei", "SimSun", "Segoe UI"],
    "darwin": ["PingFang SC", "Hiragino Sans GB", "Helvetica Neue"],
    "linux": ["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans"],
}

STYLES = """
QWidget { color: #181e2a; }
QFrame#masthead { background: transparent; border: 0; }
QLabel[role="mapState"] { color: #2663a7; font-size: 12px; font-weight: 600; }
QFrame#metrics { background: #f3f7fd; border: 0; border-radius: 10px; }
QPushButton[role="header"] { color: #2663a7; background: #eaf3ff; border-color: #d4e4f6; }
QPushButton[role="header"]:hover { background: #dcecff; }
QLabel[role="brand"] { font-size: 19px; font-weight: 600; }
QLabel[role="section"] { color: #4a5b71; font-size: 13px; font-weight: 600; }
QLabel[role="previewTitle"] { font-size: 24px; font-weight: 550; }
QLabel[role="muted"] { color: #53647a; font-size: 12px; }
QLabel[role="field"] { color: #354357; font-size: 12px; font-weight: 550; }
QLabel[role="value"] { color: #181e2a; font-size: 21px; font-weight: 600; }
QLabel[error="true"] { color: #a22630; }
QFrame[card="true"] { background: rgba(255, 255, 255, 238); border: 1px solid #e1e8f3; border-radius: 22px; }
QFrame[rule="true"] { background: #e7edf6; min-height: 1px; max-height: 1px; border: 0; }
QFrame[divider="true"] { background: #e7edf6; min-width: 1px; max-width: 1px; border: 0; }
QScrollArea, QWidget#controlBody { background: transparent; border: 0; }
QPushButton { background: #edf2f9; border: 1px solid transparent; border-radius: 13px;
              min-height: 29px; padding: 0 11px; font-size: 12px; font-weight: 550; }
QPushButton:hover { background: #e3ebf7; }
QPushButton:pressed { background: #d7e4f6; }
QPushButton:focus { border-color: #85b9f4; }
QPushButton:disabled { color: #78869b; background: #f0f3f9; }
QPushButton[role="ghost"] { color: #35618b; background: transparent; }
QPushButton[role="ghost"]:disabled { color: #78869b; }
QPushButton[role="ghost"]:hover { background: #e6effa; }
QPushButton[role="ghost"]:checked { background: #e6effa; }
QPushButton[role="map"] { background: #eaf3ff; color: #115aaf; min-height: 33px; }
QPushButton[role="map"]:hover { background: #deedff; }
QPushButton[role="map"]:disabled { background: #f0f3f9; color: #78869b; }
QPushButton[role="primary"], QPushButton[role="stop"] { background: #0874e8; color: white;
              border-radius: 19px; min-height: 43px; padding: 0 21px; font-size: 14px; font-weight: 650; }
QPushButton[role="primary"]:hover { background: #0569d5; }
QPushButton[role="stop"] { background: #bb3545; }
QPushButton[role="stop"]:hover { background: #a92839; }
QPushButton[role="primary"]:disabled, QPushButton[role="stop"]:disabled { background: #e1e8f3; color: #64768f; }
QComboBox, QLineEdit, QPlainTextEdit { border: 1px solid #e4ebf5; border-radius: 12px;
              background: #f5f8fc; min-height: 33px; padding: 0 10px; selection-background-color: #bedcff; }
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border-color: #87baf4; }
QComboBox:disabled, QLineEdit:disabled { color: #62728a; background: #f0f3f8; }
QLineEdit[error="true"] { border-color: #e28a91; }
QLineEdit#number { font-size: 16px; font-weight: 600; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView { background: #fcfdff; border: 1px solid #dce7f3;
              border-radius: 10px; padding: 5px; selection-background-color: #e1efff; selection-color: #153a65; outline: 0; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 6px;
              background: #f1f5fb; border: 1px solid #c5d3e5; }
QCheckBox::indicator:checked { background: #0874e8; border-color: #0874e8; }
QCheckBox::indicator:disabled { background: #e1e8f3; border-color: #dae4f1; }
QProgressBar { background: #eaf0f7; border: 0; border-radius: 2px; min-height: 4px; max-height: 4px; }
QProgressBar::chunk { background: #0874e8; border-radius: 2px; }
QDialog { background: #f3f7fc; }
QPlainTextEdit { padding: 10px; }
"""


def label(text, role=None, *, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def set_property(widget, name, value):
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def icon(kind, color=BLUE, size=20):
    pixels = QPixmap(size * 2, size * 2)
    pixels.fill(Qt.GlobalColor.transparent)
    pixels.setDevicePixelRatio(2)
    painter = QPainter(pixels)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.65, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if kind == "brand":
        gradient = QLinearGradient(0, 0, 24, 24)
        gradient.setColorAt(0, QColor("#5ca5ff"))
        gradient.setColorAt(1, QColor("#0874e8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(0, 0, 24, 24), 7, 7)
        pen.setColor(QColor("#ffffff"))
        painter.setPen(pen)
        route = QPainterPath(QPointF(6.5, 17.5))
        route.cubicTo(7.8, 17.5, 8.8, 8, 11.8, 7.2)
        route.cubicTo(14.5, 6.5, 15.3, 14.3, 17.7, 14.3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(route)
        painter.setBrush(QColor("#ffffff"))
        for x, y in ((6.5, 17.5), (17.7, 14.3)):
            painter.drawEllipse(QPointF(x, y), 1.2, 1.2)
    elif kind == "phone":
        painter.drawRoundedRect(QRectF(7.1, 3.6, 9.8, 16.8), 2.3, 2.3)
        painter.drawLine(QPointF(11, 6.2), QPointF(13, 6.2))
        painter.drawPoint(QPointF(12, 17.6))
    elif kind == "map":
        path = QPainterPath(QPointF(4, 7))
        path.lineTo(9, 4.5)
        path.lineTo(15, 7)
        path.lineTo(20, 4.5)
        path.lineTo(20, 17)
        path.lineTo(15, 19.5)
        path.lineTo(9, 17)
        path.lineTo(4, 19.5)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(9, 5), QPointF(9, 17))
        painter.drawLine(QPointF(15, 7), QPointF(15, 19))
    elif kind == "help":
        painter.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
        path = QPainterPath(QPointF(9.7, 9))
        path.cubicTo(10.4, 6.8, 14.8, 7.5, 14.4, 10.1)
        path.cubicTo(14.2, 11.7, 12, 11.5, 12, 13.6)
        painter.drawPath(path)
        painter.drawPoint(QPointF(12, 16.2))
    elif kind == "refresh":
        painter.drawArc(QRectF(5.2, 5.2, 13.6, 13.6), 42 * 16, 305 * 16)
        painter.drawLine(QPointF(18.7, 5.5), QPointF(18.7, 10))
        painter.drawLine(QPointF(18.7, 10), QPointF(14.1, 10))
    elif kind == "play":
        painter.setBrush(QColor(color))
        path = QPainterPath(QPointF(8, 5))
        path.lineTo(19, 12)
        path.lineTo(8, 19)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "stop":
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2.6, 2.6)
    painter.end()
    return QIcon(pixels)


def button(text, callback, *, role=None, symbol=None):
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    if symbol:
        widget.setIcon(icon(symbol, "#2162a6" if role == "header" else "#356a9e"))
        widget.setIconSize(QSize(16, 16))
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def card():
    frame = QFrame()
    frame.setProperty("card", True)
    return frame


class Surface(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#f7faff"))
        gradient.setColorAt(0.56, QColor("#edf3fb"))
        gradient.setColorAt(1, QColor("#f2f6fb"))
        painter.fillRect(self.rect(), gradient)


class BackgroundEvents(QObject):
    result = Signal(str, bool, object)
    progress = Signal(int, float, object)


class Desktop(QMainWindow):
    def __init__(self, *, discover=True, load_tiles=None):
        super().__init__()
        self.setWindowTitle("iOSRealRun")
        self.setWindowIcon(icon("brand", size=32))
        self.setStyleSheet(STYLES)
        self.load_tiles = discover if load_tiles is None else load_tiles
        self.devices = []
        self.points = []
        self.display_points = []
        self.route_name = ""
        self.distance = 0.0
        self.busy = None
        self.scanning = False
        self.scan_error = ""
        self.selected_udid = None
        self.closing = False
        self.active_laps = 0
        self.current_point = None
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.events = BackgroundEvents(self)
        self.events.result.connect(self.receive, Qt.ConnectionType.QueuedConnection)
        self.events.progress.connect(self.on_progress, Qt.ConnectionType.QueuedConnection)

        self.route_store = last_route_path() if discover else None
        self.build()
        self.load_settings()
        self.update_device_choices([])
        self.scan_timer = QTimer(self, interval=3000)
        self.scan_timer.timeout.connect(lambda: self.refresh_devices(announce=False))
        if discover:
            QTimer.singleShot(0, self, lambda: self.refresh_devices(announce=False))
            self.scan_timer.start()

        screen = self.screen().availableGeometry()
        available_width = max(640, screen.width() - 36)
        available_height = max(420, screen.height() - 60)
        self.setMinimumSize(min(770, available_width), min(450, available_height))
        self.resize(min(1080, available_width), min(700, available_height))
        self.move(screen.center() - self.rect().center())

    def build(self):
        surface = Surface()
        self.setCentralWidget(surface)
        page = QVBoxLayout(surface)
        page.setContentsMargins(16, 12, 16, 12)
        page.setSpacing(10)

        masthead = QFrame(objectName="masthead")
        header = QHBoxLayout(masthead)
        header.setContentsMargins(14, 7, 12, 7)
        header.setSpacing(9)
        brand = QLabel()
        brand.setPixmap(icon("brand", size=32).pixmap(QSize(32, 32)))
        header.addWidget(brand)
        header.addWidget(label("iOSRealRun", "brand"))
        header.addStretch()
        help_button = button("使用帮助", self.open_help, role="header", symbol="help")
        help_button.setToolTip(f"iOSRealRun {VERSION}")
        header.addWidget(help_button)
        page.addWidget(masthead)

        content = QHBoxLayout()
        content.setSpacing(12)
        page.addLayout(content, 1)
        self.controls = QScrollArea()
        self.controls.setFixedWidth(268)
        self.controls.setWidgetResizable(True)
        self.controls.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.controls.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.controls.viewport().setAutoFillBackground(False)
        panel = QWidget(objectName="controlBody")
        stack = QVBoxLayout(panel)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(12)
        stack.addWidget(self.build_device_card())
        stack.addWidget(self.build_route_card())
        stack.addStretch(1)
        self.controls.setWidget(panel)
        for widget in panel.findChildren(QWidget):
            widget.installEventFilter(self)
        content.addWidget(self.controls)
        content.addWidget(self.build_preview_card(), 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.status_label = label("", "muted", wrap=True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status_label, 1)
        self.reset_button = button("恢复定位", self.reset)
        footer.addWidget(self.reset_button)
        self.pause_button = button("暂停", self.toggle_pause)
        footer.addWidget(self.pause_button)
        self.start_button = button("开始模拟", self.start_or_stop, role="primary")
        self.start_button.setMinimumWidth(130)
        footer.addWidget(self.start_button)
        page.addLayout(footer)

        self.import_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.import_shortcut.activated.connect(self.browse_route)
        for field in (self.speed, self.laps):
            field.textChanged.connect(self.parameters_changed)

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.FocusIn:
            QTimer.singleShot(0, widget, lambda: self.controls.ensureWidgetVisible(widget, 2, 5))
        return super().eventFilter(widget, event)

    def build_device_card(self):
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 12, 15, 13)
        layout.setSpacing(7)
        heading = QHBoxLayout()
        phone = QLabel()
        phone.setPixmap(icon("phone", size=17).pixmap(QSize(17, 17)))
        heading.addWidget(phone)
        heading.addWidget(label("USB 设备", "section"))
        heading.addStretch()
        self.refresh_button = button("刷新", self.refresh_devices, role="ghost", symbol="refresh")
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)
        self.device_box = ComboBox()
        self.device_box.setAccessibleName("USB 设备")
        self.device_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device_box.setMinimumContentsLength(12)
        self.device_box.currentIndexChanged.connect(self._device_selection_changed)
        layout.addWidget(self.device_box)
        self.device_detail = label("", "muted", wrap=True)
        layout.addWidget(self.device_detail)
        self.device_action = button("", self.prepare_device, role="map")
        layout.addWidget(self.device_action, alignment=Qt.AlignmentFlag.AlignLeft)
        self.driver_help = button("安装 Apple 设备支持", self.open_driver_help, role="ghost")
        layout.addWidget(self.driver_help, alignment=Qt.AlignmentFlag.AlignLeft)
        return frame

    def build_route_card(self):
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 14, 15, 13)
        layout.setSpacing(8)
        layout.addWidget(label("路线设置", "section"))
        self.route_box = ComboBox()
        self.route_box.setAccessibleName("路线")
        self.route_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.route_box.setMinimumContentsLength(12)
        self.route_box.activated.connect(self.select_route)
        layout.addWidget(self.route_box)

        self.map_button = button("绘制路线", self.pick_route, role="map", symbol="map")
        layout.addWidget(self.map_button)
        imports = QHBoxLayout()
        imports.setSpacing(7)
        self.import_button = button("导入文件…", self.browse_route)
        self.paste_button = button("粘贴坐标…", self.paste_route)
        imports.addWidget(self.import_button, 1)
        imports.addWidget(self.paste_button, 1)
        layout.addLayout(imports)

        divider = QFrame()
        divider.setProperty("rule", True)
        layout.addWidget(divider)
        parameters = QGridLayout()
        parameters.setHorizontalSpacing(8)
        parameters.setVerticalSpacing(5)
        self.speed = QLineEdit(objectName="number")
        self.speed.setAccessibleName("速度（米/秒）")
        self.laps = QLineEdit(objectName="number")
        self.laps.setAccessibleName("圈数")
        for column, (description, field) in enumerate((("速度 · 米/秒", self.speed), ("圈数", self.laps))):
            parameters.addWidget(label(description, "field"), 0, column)
            parameters.addWidget(field, 1, column)
            parameters.setColumnStretch(column, 1)
        layout.addLayout(parameters)

        options = QHBoxLayout()
        self.closed = CheckBox("闭合路线")
        self.closed.setChecked(True)
        self.closed.toggled.connect(self.change_closure)
        options.addWidget(self.closed)
        options.addStretch()
        self.advanced_button = button("坐标设置", self.toggle_advanced, role="ghost")
        self.advanced_button.setCheckable(True)
        options.addWidget(self.advanced_button)
        layout.addLayout(options)
        self.advanced = QWidget()
        advanced = QVBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(5)
        advanced.addWidget(label("坐标系", "field"))
        self.system_box = ComboBox()
        self.system_box.setAccessibleName("坐标系")
        for display, value in SYSTEMS.items():
            self.system_box.addItem(display, value)
        self.system_box.activated.connect(self.change_coordinate_system)
        advanced.addWidget(self.system_box)
        self.advanced.hide()
        layout.addWidget(self.advanced)
        self.parameter_hint = label("", "muted", wrap=True)
        self.parameter_hint.setProperty("error", True)
        layout.addWidget(self.parameter_hint)
        return frame

    def build_preview_card(self):
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        context = QHBoxLayout()
        self.map_state = label("路线预览", "mapState")
        context.addWidget(self.map_state)
        self.tile_state = label("", "muted")
        self.tile_state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tile_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        context.addWidget(self.tile_state, 1)
        layout.addLayout(context)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        self.preview_name = label("路线预览", "previewTitle")
        self.preview_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self.preview_name, 1)
        self.map_style_box = ComboBox()
        self.map_style_box.setAccessibleName("底图样式")
        self.map_style_box.setToolTip("切换底图样式")
        for style_id, name in MAP_STYLES.items():
            self.map_style_box.addItem(name, style_id)
        self.map_style_box.setCurrentIndex(self.map_style_box.findData(DEFAULT_STYLE))
        toolbar.addWidget(self.map_style_box)
        self.canvas = MapPreview(load_tiles=self.load_tiles, style=self.map_style_box.currentData())
        self.comparison = VenueComparison(self.canvas)
        context.addWidget(self.comparison.button)
        self.canvas.changed.connect(self.update_map_status)
        self.map_style_box.currentIndexChanged.connect(
            lambda: self.canvas.set_map_style(self.map_style_box.currentData()))
        self.preview_button = button("本地预演", self.toggle_local_preview)
        self.preview_button.setToolTip("在电脑地图上预演一遍，查看速度和位置标记的轻微波动")
        toolbar.addWidget(self.preview_button)
        self.canvas.previewChanged.connect(self.update_local_preview)
        fit_button = button("全览", self.canvas.fit_route)
        fit_button.setToolTip("缩放至完整路线")
        fit_button.setAccessibleName("显示完整路线")
        toolbar.addWidget(fit_button)
        layout.addLayout(toolbar)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.comparison, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        metric_frame = QFrame(objectName="metrics")
        metrics = QHBoxLayout(metric_frame)
        metrics.setContentsMargins(13, 7, 13, 7)
        metrics.setSpacing(14)
        self.distance_text = label("—", "value")
        self.distance_caption = label("单圈距离", "muted")
        self.pace_text = label("—", "value")
        self.duration_text = label("—", "value")
        for index, (caption, item) in enumerate(((self.distance_caption, self.distance_text),
                                                 (label("配速", "muted"), self.pace_text),
                                                 (label("预计用时", "muted"), self.duration_text))):
            if index:
                rule = QFrame()
                rule.setProperty("divider", True)
                metrics.addWidget(rule)
            pair = QVBoxLayout()
            pair.setSpacing(2)
            pair.addWidget(caption)
            pair.addWidget(item)
            metrics.addLayout(pair, 1)
        layout.addWidget(metric_frame)
        return frame

    def update_map_status(self):
        self.tile_state.setText(self.canvas.status())

    def toggle_local_preview(self):
        if self.canvas.previewing:
            self.canvas.stop_preview()
        elif not self.busy and not self.closing and not self.validate_parameters():
            self.canvas.start_preview(float(self.speed.text()), self.distance)

    def update_local_preview(self):
        playing = self.canvas.previewing
        self.preview_button.setText("结束预演" if playing else "本地预演")
        if playing:
            self.map_state.setText(f"本地预演 · {self.canvas.preview_speed:.2f} 米/秒")
        elif not self.busy:
            self.map_state.setText("路线预览")

    def load_settings(self):
        settings, config_dir, warning = read_settings()
        self.interval = str(settings.get("updateInterval", 1.0))
        self.speed.setText(str(settings.get("v", DEFAULT_SPEED)))
        self.closed_laps = str(settings.get("laps", DEFAULT_LAPS))
        self.laps.setText(self.closed_laps if self.closed.isChecked() else "1")
        system = str(settings.get("coordinateSystem", "bd09")).strip().lower().replace("-", "")
        if self.system_box.findData(system) < 0:
            warning = f"{warning} 不支持配置中的坐标系，已使用 BD-09。".strip()
            system = "bd09"
        self.select_system(system)
        saved = read_last_route(self.route_store) if self.route_store else None
        if saved:
            self.set_route(*saved, remember=False)
        else:
            path = resolve_route(str(settings.get("routeConfig", "routes/ZJGEast.txt")), config_dir)
            self.open_route(path, closed=True, remember=False)
            if not self.display_points:
                self.open_route(bundled_route("ZJGEast.txt"), default_system="bd09", remember=False)
                self.show_status("默认路线无法读取，已载入紫金港东操场。", error=True)
        if warning:
            self.show_status(warning, error=True)

    def show_status(self, text, *, error=False):
        self.status_label.setText(text)
        set_property(self.status_label, "error", error)

    def open_help(self):
        QDesktopServices.openUrl(QUrl("https://github.com/BixingWu/iOSRealRun#使用方法"))

    def open_driver_help(self):
        QDesktopServices.openUrl(QUrl("https://support.apple.com/118290"))

    def selected_device(self):
        index = self.device_box.currentIndex()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def _device_selection_changed(self):
        selected = self.selected_device()
        if selected:
            self.selected_udid = selected.udid
        self.show_device()

    def show_device(self):
        device = self.selected_device()
        action = ""
        if device and device.needs_trust:
            action = "连接并信任"
        elif device and device.developer_mode is False:
            action = "显示开发者模式开关"
        detail = (device.issue or "") if device else (
            self.scan_error or "连接并解锁设备。"
        )
        self.device_detail.setText(detail)
        self.device_detail.setVisible(bool(detail))
        self.device_action.setText(action)
        self.device_action.setVisible(bool(action))
        self.driver_help.setVisible(not device and sys.platform == "win32")
        self.update_controls()

    def update_device_choices(self, devices, error=""):
        self.devices = devices
        self.scan_error = error
        labels = [f"{device.name} · {device.version}" if device.version else device.name for device in devices]
        groups = {}
        for index, name in enumerate(labels):
            groups.setdefault(name, []).append(index)
        for name, indices in groups.items():
            if len(indices) > 1:
                for number, index in enumerate(sorted(indices, key=lambda item: devices[item].udid), 1):
                    labels[index] = f"{name} · {number}"
        self.device_box.blockSignals(True)
        self.device_box.clear()
        if devices:
            self.device_box.addItems(labels)
            index = next((index for index, device in enumerate(devices) if device.udid == self.selected_udid), None)
            if index is None:
                index = next((index for index, device in enumerate(devices) if not device.issue), 0)
            self.device_box.setCurrentIndex(index)
        else:
            self.device_box.addItem("未连接设备")
        self.device_box.blockSignals(False)
        self._device_selection_changed()

    def refresh_devices(self, *, announce=True):
        if self.closing or self.busy or self.scanning:
            return
        self.scanning = True
        if announce:
            self.device_detail.setText("正在查找 USB 设备…")
            self.device_detail.show()
        self.submit("scan", list_devices())

    def prepare_device(self):
        device = self.selected_device()
        if not device or self.busy or self.scanning:
            return
        if device.needs_trust:
            self.submit("connect", connect_device(device.udid), "请在设备上确认信任。")
        elif device.developer_mode is False:
            self.submit("reveal", reveal_developer_mode(device.udid), "正在请求显示开发者模式开关…")

    def select_route(self, index):
        name = self.route_box.itemText(index)
        if name in ROUTES:
            self.open_route(bundled_route(ROUTES[name]), default_system="bd09")

    def select_system(self, system):
        index = self.system_box.findData(system)
        self.system_box.setCurrentIndex(index if index >= 0 else self.system_box.findData("bd09"))

    def toggle_advanced(self, checked):
        self.advanced.setVisible(checked)
        if checked:
            QTimer.singleShot(0, self, lambda: self.controls.ensureWidgetVisible(self.system_box, 4, 7))

    def change_coordinate_system(self):
        self.show_status("")
        self.update_route()
        self.remember_route()

    def change_closure(self, checked):
        self.update_lap_mode(checked)
        self.change_coordinate_system()

    def update_lap_mode(self, closed):
        if not closed:
            self.closed_laps = self.laps.text()
        self.laps.setText(self.closed_laps if closed else "1")

    def pick_route(self):
        if self.busy or self.closing:
            return
        reference = self.display_points
        if self.closed.isChecked() and reference and reference[-1] != reference[0]:
            reference = reference + reference[:1]

        def apply(points):
            name = SHAPES.get(dialog.canvas.shape, "地图路线")
            self.set_route(points, name, "wgs84", dialog.canvas.route_closed)
            self.comparison.copy_view(dialog.comparison)

        dialog = open_map_picker(self, reference, apply,
                                 style=self.map_style_box.currentData(), load_tiles=self.load_tiles,
                                 venues=self.comparison.entries.values())
        dialog.comparison.copy_view(self.comparison)
        dialog.mapStyleChanged.connect(
            lambda style: self.map_style_box.setCurrentIndex(self.map_style_box.findData(style)))
        return dialog

    def browse_route(self):
        if self.busy or self.closing:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "导入路线", "", "路线文件 (*.txt *.json *.gpx);;所有文件 (*)")
        if filename:
            path = Path(filename)
            if self.open_route(path) and path.suffix.lower() != ".gpx":
                self.advanced_button.setChecked(True)
                self.toggle_advanced(True)

    def open_route(self, path, *, default_system=None, closed=None, remember=True):
        try:
            name = next((label_text for label_text, filename in ROUTES.items() if filename == path.name), None)
            # PyInstaller's macOS bundle can symlink route files from Frameworks to Resources.
            built_in = name is not None and path.resolve() == bundled_route(path.name).resolve()
            if closed is None:
                closed = built_in
            points, system = load_route(path, preserve_endpoint=not closed)
        except (OSError, ValueError) as error:
            self.update_route_choices()
            self.show_status(f"无法打开 {path.name}。{error}", error=True)
            return False
        self.set_route(points, name if built_in else path.name, system or default_system, closed, remember=remember)
        return True

    def paste_route(self):
        if self.busy or self.closing:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("粘贴坐标")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.resize(530, 325)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(10)
        layout.addWidget(label("每个坐标点由 lat（纬度）和 lng（经度）组成。", "muted", wrap=True))
        field = QPlainTextEdit()
        field.setPlaceholderText('[{"lat": 30.1, "lng": 120.1}, {"lat": 30.101, "lng": 120.101}]')
        field.setAccessibleName("路线坐标")
        layout.addWidget(field, 1)
        system_row = QHBoxLayout()
        system_row.addWidget(label("坐标系", "field"))
        system_box = ComboBox()
        system_box.setAccessibleName("粘贴坐标系")
        for name, code in SYSTEMS.items():
            system_box.addItem(name, code)
        system_box.setCurrentIndex(system_box.findData("bd09"))
        system_row.addWidget(system_box, 1)
        layout.addLayout(system_row)
        error_label = label("", "muted", wrap=True)
        error_label.setProperty("error", True)
        bottom = QHBoxLayout()
        bottom.addWidget(error_label, 1)
        bottom.addWidget(button("取消", dialog.reject))

        def use_coordinates():
            if field.document().characterCount() - 1 > MAX_ROUTE_BYTES:
                error_label.setText("路线内容不能超过 2 MiB。")
                return
            try:
                points = parse_route_text(field.toPlainText(), preserve_endpoint=True)
            except ValueError as error:
                error_label.setText(str(error))
                return
            self.set_route(points, "粘贴的路线", system_box.currentData(), closed=False)
            dialog.accept()

        bottom.addWidget(button("使用路线", use_coordinates, role="primary"))
        layout.addLayout(bottom)
        dialog.open()
        field.setFocus()

    def update_route_choices(self):
        self.route_box.blockSignals(True)
        self.route_box.clear()
        self.route_box.addItems(list(ROUTES))
        if self.route_name and self.route_name not in ROUTES:
            name = self.route_name if len(self.route_name) <= 26 else f"{self.route_name[:17]}…{self.route_name[-7:]}"
            self.route_box.insertItem(0, name)
            self.route_box.setCurrentIndex(0)
        else:
            self.route_box.setCurrentIndex(self.route_box.findText(self.route_name))
        self.route_box.blockSignals(False)

    def set_route(self, points, name, system=None, closed=True, *, remember=True):
        if system:
            self.select_system(system)
        if self.closed.isChecked() != closed:
            self.closed.blockSignals(True)
            self.closed.setChecked(closed)
            self.closed.blockSignals(False)
            self.update_lap_mode(closed)
        self.points = points
        self.route_name = name
        self.comparison.select_route(name)
        self.update_route_choices()
        self.show_status("")
        self.update_route()
        if remember:
            self.remember_route()

    def remember_route(self):
        if not self.route_store or not self.display_points:
            return
        try:
            save_last_route(self.route_store, self.points, self.route_name, self.system_box.currentData(), self.closed.isChecked())
        except (OSError, ValueError):
            self.show_status("路线可用，但未能保存到此电脑。", error=True)

    def update_route(self):
        self.current_point = None
        self.progress_bar.hide()
        self.display_points = []
        self.distance = 0.0
        try:
            points = [to_wgs84(point, self.system_box.currentData()) for point in self.points]
            self.distance = route_length(points, closed=self.closed.isChecked())
            if not self.distance:
                raise ValueError("路线长度需大于零。")
            self.display_points = points
            name = self.route_name
            self.preview_name.setText(name if len(name) <= 36 else f"{name[:25]}…{name[-9:]}")
            self.preview_name.setToolTip(name)
        except (ValueError, OverflowError, ZeroDivisionError) as error:
            self.preview_name.setText("路线预览")
            self.preview_name.setToolTip("")
            self.show_status(str(error), error=True)
        self.canvas.set_route(self.display_points, self.closed.isChecked())
        self.parameters_changed()

    def validate_parameters(self):
        error = ""
        for widget, value, convert, low, high, message in (
            (self.speed, self.speed.text(), float, 0.1, 30, "速度范围为 0.1–30 米/秒。"),
            (self.laps, self.laps.text() if self.closed.isChecked() else "1", int, 0, 999, "圈数需为 0–999 的整数。"),
        ):
            try:
                valid = low <= convert(value) <= high
            except (ValueError, OverflowError):
                valid = False
            set_property(widget, "error", not valid)
            if not valid and not error:
                error = message
        try:
            interval_valid = 0.1 <= float(self.interval) <= 10
        except (ValueError, OverflowError):
            interval_valid = False
        return error or ("" if interval_valid else "配置中的更新间隔需为 0.1–10 秒。")

    def parameters_changed(self):
        self.canvas.stop_preview()
        self.update_estimates()
        self.update_controls()

    def update_estimates(self):
        try:
            speed = float(self.speed.text())
            if not 0.1 <= speed <= 30:
                raise ValueError
            pace = round(1000 / speed)
            self.pace_text.setText(f"{pace // 60}:{pace % 60:02d} /km")
        except (ValueError, OverflowError):
            speed = None
            self.pace_text.setText("—")
        try:
            laps = int(self.laps.text()) if self.closed.isChecked() else 1
            if not 0 <= laps <= 999:
                raise ValueError
        except ValueError:
            laps = None
        if self.distance > 0:
            self.distance_text.setText(f"{self.distance:.0f} m" if self.distance < 1000 else
                                       f"{self.distance / 1000:.2f} km")
        else:
            self.distance_text.setText("—")
        self.distance_caption.setText("单圈距离" if self.closed.isChecked() else "路线距离")
        if laps == 0 and speed and self.distance:
            duration = "持续"
        elif laps and speed and self.distance:
            seconds = max(1, round(self.distance * laps / speed))
            minutes, second = divmod(seconds, 60)
            hours, minute = divmod(minutes, 60)
            duration = f"{hours}:{minute:02d}:{second:02d}" if hours else f"{minute}:{second:02d}"
        else:
            duration = "—"
        self.duration_text.setText(duration)

    def update_controls(self):
        device = self.selected_device()
        ready = device is not None and device.ready
        running = self.busy == "replay"
        idle = self.busy is None and not self.closing
        self.refresh_button.setEnabled(idle and not self.scanning)
        self.device_action.setEnabled(idle and not self.scanning)
        self.device_box.setEnabled(idle and bool(self.devices))
        for control in (self.route_box, self.system_box, self.speed, self.import_button,
                        self.paste_button, self.map_button, self.closed, self.advanced_button):
            control.setEnabled(idle)
        self.laps.setEnabled(idle and self.closed.isChecked())
        self.laps.setToolTip("0 表示持续循环" if self.closed.isChecked() else "开放路线只运行一遍")
        error = self.validate_parameters()
        self.parameter_hint.setText(error)
        self.parameter_hint.setVisible(bool(error))
        self.reset_button.setVisible(ready and idle)
        state = "路线预览"
        if running:
            if self.stop.is_set():
                state = "正在停止"
            elif self.paused.is_set():
                state = "模拟已暂停"
            elif self.current_point is None:
                state = "正在连接"
            else:
                state = "实时位置"
        self.preview_button.setEnabled(idle and bool(self.display_points) and not error)
        if not self.canvas.previewing:
            self.map_state.setText(state)
        self.pause_button.setVisible(running and self.current_point is not None)
        self.pause_button.setEnabled(running and not self.stop.is_set())
        stopping = running and self.stop.is_set()
        role = "stop" if running else "primary"
        set_property(self.start_button, "role", role)
        caption = "停止中…" if stopping else "停止" if running else "开始模拟"
        self.start_button.setText(caption)
        enabled = (running and not stopping) or (idle and ready and bool(self.display_points) and not error)
        self.start_button.setEnabled(enabled)
        self.start_button.setIcon(icon("stop" if running else "play", "#ffffff" if enabled else "#63758e", 16))

    def start_or_stop(self):
        if self.busy == "replay":
            if not self.stop.is_set():
                self.stop.set()
                self.paused.clear()
                self.show_status("正在停止并恢复定位…" if self.current_point else "正在停止…")
                self.update_controls()
            return
        device = self.selected_device()
        if self.busy or self.closing or not device or not device.ready:
            return
        if not self.display_points or self.validate_parameters():
            return
        closed = self.closed.isChecked()
        self.active_laps = int(self.laps.text()) if closed else 1
        self.stop.clear()
        self.paused.clear()
        self.current_point = None
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.submit("replay", replay_route(
            device.udid, self.points, speed=float(self.speed.text()), laps=self.active_laps,
            interval=float(self.interval), coordinate_system=self.system_box.currentData(),
            stop_requested=self.stop.is_set, pause_requested=self.paused.is_set,
            on_progress=self.events.progress.emit, closed=closed,
        ), f"正在准备 iOS {device.version} 定位服务…" if device.uses_legacy_location else "正在建立设备连接…")

    def toggle_pause(self):
        if self.busy != "replay" or self.stop.is_set():
            return
        if self.paused.is_set():
            self.paused.clear()
            self.pause_button.setText("暂停")
            self.show_status("继续模拟")
        else:
            self.paused.set()
            self.pause_button.setText("继续")
            self.show_status("已暂停")
        self.update_controls()

    def reset(self):
        device = self.selected_device()
        if device and not self.busy and not self.closing:
            self.submit("reset", reset_location(device.udid), "正在恢复设备定位…")

    def submit(self, action, operation, status=None):
        if action != "scan":
            self.busy = action
            self.canvas.stop_preview()
        if status:
            self.show_status(status)
        self.update_controls()
        events = self.events

        def worker():
            try:
                value = asyncio.run(operation)
            except Exception as error:
                result = False, str(error) or type(error).__name__
            else:
                result = True, value
            try:
                events.result.emit(action, *result)
            except RuntimeError:
                # A read-only scan may finish after its window has closed.
                pass

        threading.Thread(target=worker, name=f"iosrealrun-{action}", daemon=True).start()

    def on_progress(self, lap, fraction, point):
        if self.busy != "replay":
            return
        first = self.current_point is None
        self.current_point = point
        amount = (lap - 1 + fraction) / self.active_laps if self.active_laps else fraction
        self.progress_bar.setValue(round(amount * 1000))
        self.canvas.set_marker(point)
        if first:
            self.update_controls()
        if not self.paused.is_set() and not self.stop.is_set():
            count = f" / {self.active_laps}" if self.active_laps else ""
            self.show_status(f"正在模拟 · 第 {lap}{count} 圈 · {fraction:.0%}" if self.closed.isChecked()
                             else f"正在模拟 · {fraction:.0%}")

    def receive(self, action, success, value):
        if action == "scan":
            self.scanning = False
            if not self.busy and not self.closing:
                devices, error = (value, "") if success else ([], value)
                if self.devices != devices or self.scan_error != error or not self.device_box.count():
                    self.update_device_choices(devices, error)
                else:
                    self.show_device()
            else:
                self.update_controls()
            return
        self.busy = None
        self.pause_button.setText("暂停")
        if action == "replay":
            self.current_point = None
            self.canvas.set_marker(None)
            self.progress_bar.hide()
        if not success:
            self.show_status(value, error=True)
            if self.closing:
                QMessageBox.warning(self, "iOSRealRun", value)
        elif action == "connect":
            devices = [value if device.udid == value.udid else device for device in self.devices]
            self.update_device_choices(devices)
            self.show_status(value.issue or "设备已连接")
        elif action == "reveal":
            self.show_status("在设备上开启开发者模式，按提示重启并确认。")
        elif action == "reset":
            self.show_status("已发送恢复定位指令")
        elif action == "replay":
            if not value:
                self.show_status("已停止")
            else:
                self.show_status("已停止，已发送恢复定位指令" if self.stop.is_set() else "路线已完成，已发送恢复定位指令")
        self.update_controls()
        if self.closing:
            self.close()
        elif action in ("replay", "reveal"):
            self.refresh_devices(announce=False)

    def closeEvent(self, event):
        if self.busy is None:
            self.scan_timer.stop()
            self.canvas.stop_preview()
            self.canvas.stop()
            event.accept()
            return
        self.closing = True
        if self.busy == "replay":
            self.start_or_stop()
        else:
            self.show_status("正在结束设备操作，完成后自动关闭…")
        event.ignore()


def self_test(window):
    from mapbox_vector_tile import decode
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
    from iosrealrun.desktop_device import Device

    if UserspaceRsdTunnel is None:
        raise RuntimeError("Cannot import the device tunnel.")
    if decode(b""):
        raise RuntimeError("Expected an empty vector tile to have no map layers.")
    for path in ROUTES.values():
        if not window.open_route(bundled_route(path), default_system="bd09", remember=False) or not window.distance:
            raise RuntimeError(f"Cannot load bundled route {path}.")
        if not window.closed.isChecked():
            raise RuntimeError(f"Bundled route {path} did not load as a closed route.")
    window.laps.setText("0")
    if window.duration_text.text() != "持续" or window.start_button.isEnabled():
        raise RuntimeError("No-device controls are not in their expected state.")
    window.preview_button.click()
    if not window.canvas.previewing or window.canvas.marker is not None:
        raise RuntimeError("The local map preview did not start independently of the device.")
    window.preview_button.click()
    window.receive("scan", True, [Device("self-test", "iPhone", "15.6")])
    if not window.start_button.isEnabled() or not window.reset_button.isVisible() or window.device_action.isVisible():
        raise RuntimeError("iOS 15.6 controls unexpectedly require Developer Mode.")
    window.receive("scan", True, [])
    picker = open_map_picker(window, window.display_points, lambda _: None, load_tiles=False)
    QApplication.processEvents()
    picker.close()


def main():
    parser = argparse.ArgumentParser(description="iOSRealRun desktop")
    parser.add_argument("--version", action="version", version=f"iOSRealRun {VERSION}")
    parser.add_argument("--self-test", action="store_true", help="check Qt, bundled routes and the map picker")
    parser.add_argument("--screenshot", type=Path, help="save the desktop window as a PNG without probing hardware")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("iOSRealRun")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    font = QFont()
    if sys.platform in FONT_FAMILIES:
        font.setFamilies(FONT_FAMILIES[sys.platform])
    font.setPointSize(10)
    app.setFont(font)
    window = Desktop(discover=not (args.self_test or args.screenshot))
    if args.screenshot:
        window.resize(1080, 700)
    window.show()
    window.canvas.setFocus()
    app.processEvents()
    if args.self_test:
        self_test(window)
    if args.screenshot:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(args.screenshot)):
            raise RuntimeError(f"Cannot save {args.screenshot}.")
    if args.self_test or args.screenshot:
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
