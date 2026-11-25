"""Venue selection shared by the route editor and the replay map."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QPushButton, QFileDialog

from iosrealrun.map_picker import TILE_SIZE, _project, _wrapped_delta
from iosrealrun.venue_registration import Registration, load_venues, read_locations


class VenueOverlay(QPushButton):
    alignmentChanged = Signal(str)

    def __init__(self, canvas, venues=None, alignment_dir=None):
        super().__init__("场地范围")
        self.canvas = canvas
        self.alignment_dir = alignment_dir
        self.entries = {v.title: v for v in (load_venues() if venues is None else venues)}
        self.selected = None
        self.show_outline = True
        self.ring = []
        self.note = ""
        self.setAccessibleName("场地范围与对齐设置")
        self.setAutoDefault(False)
        menu = QMenu(self)
        menu.aboutToShow.connect(self._build_menu)
        self.setMenu(menu)
        self.refresh()

    @property
    def title(self):
        return self.selected.title if self.selected else ""

    def _geometry(self, venue):
        if len(venue.outline) < 3:
            return [], "待补场地轮廓"
        try:
            locations = read_locations(venue, self.alignment_dir)
            fit = Registration(venue.landmarks, locations)
        except ValueError:
            return [], "地标待对齐"
        count = sum(p is not None for p in locations)
        return fit.ring(venue), f"图上估测 · {count} 个地标 · 拟合差 {fit.rms_metres:.1f} 米"

    def refresh(self, *, fit=False):
        self.ring, self.note = self._geometry(self.selected) if self.selected else ([], "请选择场地")
        self.canvas.set_venue_outline(self.ring if self.show_outline else [], fit=fit)
        self.setToolTip(" · ".join(filter(None, (self.title, self.note))))

    def select_route(self, name, points=(), *, fit=False):
        self.selected = next((v for v in self.entries.values() if name == v.title or name in v.routes), None)
        if not self.selected and points:
            # Restore the visual layer for a named drawing after restarting the app.
            first_x, first_y = _project(points[0], 0)
            for venue in self.entries.values():
                ring, _ = self._geometry(venue)
                if ring:
                    offsets = [(_wrapped_delta(x, first_x, TILE_SIZE), y - first_y)
                               for x, y in (_project(point, 0) for point in ring)]
                    xs, ys = zip(*offsets)
                    if min(xs) <= 0 <= max(xs) and min(ys) <= 0 <= max(ys):
                        self.selected = venue
                        break
        self.refresh(fit=fit)

    def copy_view(self, other, *, focus_venue=False):
        self.entries.update(other.entries)
        self.selected, self.show_outline = other.selected, other.show_outline
        self.refresh(fit=not focus_venue)
        if focus_venue and self.show_outline and self.ring:
            self.canvas.frame_landmarks(self.ring)

    def _choose(self, venue):
        self.selected = venue
        self.show_outline = True
        self.refresh()
        if self.ring:
            self.canvas.frame_landmarks(self.ring)
        elif venue.center:
            self.canvas.center_on(venue.center)

    def _visible(self, value):
        self.show_outline = value
        self.refresh()

    def _build_menu(self):
        menu = self.menu()
        menu.clear()
        if self.selected:
            menu.addAction(self.title + " · " + self.note).setEnabled(False)
            if self.selected.credit:
                menu.addAction(self.selected.credit).setEnabled(False)
        visible = menu.addAction("显示红色参考范围")
        visible.setCheckable(True)
        visible.setChecked(self.show_outline and bool(self.ring))
        visible.setEnabled(bool(self.ring))
        visible.triggered.connect(self._visible)
        full = menu.addAction("全览场地范围")
        full.setEnabled(bool(self.ring))
        full.triggered.connect(lambda: self._choose(self.selected))
        choose = menu.addMenu("选择场地")
        choose.setEnabled(bool(self.entries))
        for venue in self.entries.values():
            action = choose.addAction(venue.title if venue.outline else venue.title + "（待补轮廓）")
            action.setCheckable(True)
            action.setChecked(venue == self.selected)
            action.triggered.connect(lambda checked=False, v=venue: self._choose(v))
        adjust = menu.addAction("对齐地标…")
        adjust.setEnabled(bool(self.selected and self.selected.outline and len(self.selected.landmarks) >= 3))
        adjust.triggered.connect(self.open_alignment)
        menu.addSeparator()
        menu.addAction("打开场地数据目录…").triggered.connect(self._import_folder)

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择含 boundaries.json 的场地目录")
        if folder:
            available = load_venues(Path(folder))
            self.entries.update((venue.title, venue) for venue in available)
            if available:
                self._choose(next((v for v in available if v.outline), available[0]))

    def open_alignment(self):
        from iosrealrun.venue_alignment import AlignmentDialog

        venue = self.selected
        if not venue or not venue.outline or len(venue.landmarks) < 3:
            return
        dialog = AlignmentDialog(self.window(), venue, self.canvas, self.alignment_dir)
        dialog.accepted.connect(lambda: self.reload_alignment(venue.title))
        dialog.accepted.connect(lambda: self.alignmentChanged.emit(venue.title))
        dialog.open()
        return dialog

    def reload_alignment(self, title):
        if title == self.title:
            self.refresh()
