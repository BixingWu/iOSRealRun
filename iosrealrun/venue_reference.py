"""Local venue screenshots for side-by-side comparison with a map."""

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from iosrealrun.paths import config_directory
from iosrealrun.qt_controls import ComboBox


@dataclass(frozen=True)
class Venue:
    title: str
    file: Path | None = None
    routes: tuple = ()
    map_top: float = 0


def load_venues(directory=None):
    folder = Path(directory) if directory is not None else config_directory() / "场地参考"
    try:
        files = {f.name: f for f in sorted(folder.iterdir())
                 if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")}
    except OSError:
        return ()
    try:
        metadata = json.loads((folder / "index.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        metadata = []
    venues = {}
    for item in metadata if isinstance(metadata, list) else ():
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            continue
        filename = item.get("image")
        path = files.pop(filename, None) if isinstance(filename, str) else None
        routes = item.get("routes", [])
        top = item.get("map_top", 0)
        venues[item["title"]] = Venue(item["title"], path,
                                     tuple(s for s in routes if isinstance(s, str)) if isinstance(routes, list) else (),
                                     top if isinstance(top, (float, int)) and 0 <= top < 1 else 0)
    for file in files.values():
        venues.setdefault(file.stem, Venue(file.stem, file))
    return tuple(venues.values())


class ReferenceImage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.picture = QPixmap()
        self.message = "选择本地场地截图"
        self.setAccessibleName("场地截图")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f2f6fc"))
        if self.picture.isNull():
            painter.setPen(QColor("#53647a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        size = self.picture.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(QRectF(self.rect()).center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self.picture, QRectF(self.picture.rect()))


class VenueComparison(QSplitter):
    def __init__(self, canvas, venues=None):
        super().__init__(Qt.Orientation.Horizontal)
        self.addWidget(canvas)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(5)
        self.panel = QFrame()
        self.panel.setMinimumWidth(150)
        column = QVBoxLayout(self.panel)
        column.setContentsMargins(3, 1, 3, 1)
        column.setSpacing(4)
        self.selector = ComboBox()
        self.selector.setAccessibleName("参考场地")
        self.selector.setPlaceholderText("选择场地")
        self.selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column.addWidget(self.selector)
        self.image = ReferenceImage()
        column.addWidget(self.image, 1)
        self.caption = QLabel("原图对照 · 未标定")
        self.caption.setToolTip("红线在截图中的原位置显示，图像像素没有地理坐标")
        self.caption.setStyleSheet("color: #53647a; font-size: 11px;")
        column.addWidget(self.caption)
        actions = QHBoxLayout()
        self.open_button = QPushButton("打开截图…")
        self.open_button.clicked.connect(self.open_file)
        self.enlarge_button = QPushButton("放大")
        self.enlarge_button.clicked.connect(self.enlarge)
        for button in (self.open_button, self.enlarge_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        column.addLayout(actions)
        self.addWidget(self.panel)
        self.setStretchFactor(0, 3)
        self.setStretchFactor(1, 1)
        self.setSizes([580, 220])
        self.button = QPushButton("场地对照")
        self.button.setAutoDefault(False)
        self.button.setCheckable(True)
        self.button.setAccessibleName("显示场地截图对照")
        self.button.toggled.connect(self.panel.setVisible)
        self._user_visibility = None
        self.button.clicked.connect(self._remember_visibility)
        self.panel.hide()
        self.entries = {}
        for venue in load_venues() if venues is None else venues:
            self._add(venue)
        self.selector.currentTextChanged.connect(self._show_reference)
        self._show_reference()

    def _remember_visibility(self, visible):
        self._user_visibility = visible

    def _add(self, venue):
        previous = self.entries.get(venue.title)
        self.entries[venue.title] = venue
        if previous is None:
            self.selector.addItem(venue.title)
        elif previous != venue and self.selector.currentText() == venue.title:
            self._show_reference()

    def select_route(self, name):
        for entry in self.entries.values():
            if name == entry.title or name in entry.routes:
                self.selector.setCurrentText(entry.title)
                if self._user_visibility is None:
                    self.button.setChecked(entry.file is not None)
                return
        if self._user_visibility is None:
            self.button.setChecked(False)
            self.selector.setCurrentIndex(-1)

    def copy_view(self, source):
        entry = source.entries.get(source.selector.currentText())
        if entry:
            self._add(entry)
            self.selector.setCurrentText(entry.title)
        else:
            self.selector.setCurrentIndex(-1)
        self._user_visibility = source._user_visibility
        self.button.setChecked(source.button.isChecked())

    def _show_reference(self):
        entry = self.entries.get(self.selector.currentText())
        self.image.picture = QPixmap()
        self.image.message = "该场地待补截图" if entry else "选择本地场地截图"
        if entry and entry.file:
            reader = QImageReader(str(entry.file))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                self.image.message = "截图无法读取"
            else:
                top = int(image.height() * entry.map_top)
                self.image.picture = QPixmap.fromImage(image.copy(0, top, image.width(), image.height() - top))
        self.enlarge_button.setEnabled(not self.image.picture.isNull())
        self.image.update()

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "打开场地截图", "", "地图截图 (*.jpg *.jpeg *.png *.webp)")
        if filename:
            path = Path(filename)
            self._add(Venue(path.stem, path))
            self.selector.setCurrentText(path.stem)

    def enlarge(self):
        if self.image.picture.isNull():
            return
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(self.selector.currentText() + " · 场地截图")
        view = ReferenceImage()
        view.picture = self.image.picture
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(view)
        screen = self.screen().availableGeometry()
        dialog.resize(min(850, screen.width() - 40), min(950, screen.height() - 64))
        dialog.show()
