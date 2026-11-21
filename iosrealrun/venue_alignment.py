"""Adjust named landmarks directly on the basemap and preview the resulting outline."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from iosrealrun.qt_controls import ComboBox
from iosrealrun.qt_map_picker import PICKER_STYLE, _MapCanvas
from iosrealrun.venue_registration import Registration, read_locations, save_locations


class LandmarkMap(_MapCanvas):
    picked = Signal(dict)

    def __init__(self, parent, seed, source):
        super().__init__(parent, seed, False, source._load_tiles, editable=False, style=source.map_style)
        self._auto_fit = False
        self.locations = []
        self.active = 0
        self.setAccessibleName("地标对齐地图")
        self.setAccessibleDescription("点击底图设置所选地标，拖动平移，滚轮缩放。")

    def mouseReleaseEvent(self, event):
        click = self._press is not None and not self._dragging and event.button() == Qt.MouseButton.LeftButton
        super().mouseReleaseEvent(event)
        if click and QRectF(self.rect()).contains(event.position()):
            point = self._map_point(event.position())
            if point is not None:
                self.picked.emit(point)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, point in enumerate(self.locations):
            if not point:
                continue
            pos = self._screen_path([point]).first()
            bubble = QRectF(pos.x()+3, pos.y()-22, 19, 19)
            color = QColor("#075bcc" if index == self.active else "#455d76")
            painter.setBrush(color)
            painter.setPen(QPen(QColor("white"), 1.2))
            painter.drawEllipse(pos, 3.2, 3.2)
            painter.drawEllipse(bubble)
            painter.drawText(bubble, Qt.AlignmentFlag.AlignCenter, str(index+1))


class AlignmentDialog(QDialog):
    def __init__(self, parent, venue, source, directory):
        super().__init__(parent)
        self.setWindowTitle(f"对齐地标 · {venue.title}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(PICKER_STYLE)
        self.venue, self.directory = venue, directory
        self.locations = read_locations(venue, directory)
        seed = [p for p in self.locations if p]
        if not seed:
            seed = [venue.center or source._map_point(QPointF(source.rect().center()))]
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("在底图上点击所选地标的位置"), 1)
        self.selector = ComboBox()
        self.selector.setAccessibleName("待对齐地标")
        for index, mark in enumerate(venue.landmarks, 1):
            self.selector.addItem(f"{index}  {mark.name}")
        heading.addWidget(self.selector)
        layout.addLayout(heading)
        self.canvas = LandmarkMap(self, seed, source)
        self.canvas.picked.connect(self.place)
        self.selector.currentIndexChanged.connect(self.select_landmark)
        layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        initial = QPushButton("恢复初始位置")
        initial.clicked.connect(self.reset_positions)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("保存对齐")
        self.save_button.setObjectName("mapApply")
        self.save_button.clicked.connect(self.save)
        for button in (initial, cancel, self.save_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        layout.addLayout(footer)
        self.refresh()
        screen = self.screen().availableGeometry()
        self.resize(min(810, screen.width()-45), min(585, screen.height()-55))

    def select_landmark(self, index):
        self.canvas.active = index
        self.canvas.update()

    def place(self, point):
        index = self.selector.currentIndex()
        self.locations[index] = point
        self.selector.setCurrentIndex((index + 1) % len(self.locations))
        self.refresh()

    def reset_positions(self):
        self.locations = self.venue.base_locations()
        self.refresh()

    def refresh(self):
        self.canvas.locations = self.locations
        try:
            fit = Registration(self.venue.landmarks, self.locations)
            ring = fit.ring(self.venue)
            self.summary.setText(f"地标拟合差约 {fit.rms_metres:.1f} 米")
            self.summary.setToolTip("反映所选地标之间的一致程度。场地范围来自地图估测。")
        except ValueError as error:
            ring = []
            self.summary.setText(str(error))
        self.canvas.set_venue_outline(ring)
        self.save_button.setEnabled(bool(ring))

    def save(self):
        try:
            save_locations(self.venue, self.locations, self.directory)
        except (OSError, ValueError) as error:
            self.summary.setText(f"无法保存对齐位置。{error}")
            return
        self.accept()

    def done(self, result):
        self.canvas.stop()
        super().done(result)
