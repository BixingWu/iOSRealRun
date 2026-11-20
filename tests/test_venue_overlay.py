import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iosrealrun.map_picker import _project, _unproject
from iosrealrun.paths import RESOURCE_ROOT
from iosrealrun.qt_desktop import Desktop
from iosrealrun.qt_map_picker import MapPreview
from iosrealrun.venue_overlay import VenueOverlay
from iosrealrun.venue_registration import (Landmark, Registration, Venue, alignment_path, load_venues,
                                           read_locations, save_locations)


def example(*, dateline=False):
    center = {"lat": 30.3078, "lng": 179.9999 if dateline else 120.0783}
    x, y = _project(center, 0)
    outline = ((-80, -60), (80, -60), (80, 60), (12, 60), (12, 8), (-12, 8), (-12, 60), (-80, 60))
    anchors = ((-60, -40), (60, -40), (60, 40), (-60, 40))
    locations = [_unproject(x + .000006*s - .000002*t, y + .000002*s + .000006*t, 0) for s, t in anchors]
    marks = tuple(Landmark(str(i), p, loc) for i, (p, loc) in enumerate(zip(anchors, locations)))
    return Venue("示例场地", ("紫金港东操场", "紫金港西操场"), outline, marks, center)


class VenueOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_registration_preserves_notches_across_the_date_line(self):
        venue = example(dateline=True)
        locations = venue.base_locations()
        fit = Registration(venue.landmarks, locations)
        self.assertLess(fit.rms_metres, .00001)
        for i, mark in enumerate(venue.landmarks):
            estimate = fit.project(mark.pixel)
            self.assertAlmostEqual(estimate["lng"], locations[i]["lng"], places=8)
            self.assertAlmostEqual(estimate["lat"], locations[i]["lat"], places=8)
        ring = fit.ring(venue)
        self.assertEqual(len(ring), 8)
        self.assertLess(min(p["lng"] for p in ring), -179)
        self.assertGreater(max(p["lng"] for p in ring), 179)
        with self.assertRaises(ValueError):
            Registration(venue.landmarks, [None, None, *locations[2:]])
        with self.assertRaises(ValueError):
            Registration(venue.landmarks, [locations[0]]*4)
        with self.assertRaises(ValueError):
            Registration([Landmark("路口", (i, 0), p) for i,p in enumerate(locations)], locations)

    def test_catalog_merges_aliases_and_keeps_unregistered_sites_empty(self):
        (self.folder / "index.json").write_text(json.dumps([
            {"title":"操场", "image":"图.jpg", "routes":["东", "西"]}, {"title":"待补场地"}]), encoding="utf-8")
        v = example()
        marks = [{"name":m.name, "pixel":m.pixel, "wgs84":[m.location["lng"], m.location["lat"]]} for m in v.landmarks]
        (self.folder / "boundaries.json").write_text(json.dumps([
            {"title":"操场","outline":v.outline,"landmarks":marks},
            {"title":"坏坐标","outline":[[0,0]],"landmarks":[{"name":"角","pixel":[1,1],"wgs84":[300,99]}]}]),
            encoding="utf-8")
        ready, pending, bad = load_venues(self.folder)
        self.assertEqual(ready.routes, ("东","西"))
        self.assertEqual(ready.outline, v.outline)
        self.assertFalse(pending.outline or bad.outline)
        original = ready.base_locations()
        save_locations(ready, original, self.folder)
        file = alignment_path(ready, self.folder)
        self.assertTrue(file.is_file())
        file.write_text("corrupt", encoding="utf-8")
        self.assertEqual(read_locations(ready, self.folder), original)
        self.assertFalse(load_venues(self.folder / "missing"))

    def test_red_edge_follows_zoom_and_pan_without_changing_route(self):
        preview = MapPreview(load_tiles=False, style="plain")
        self.addCleanup(preview.close)
        preview.resize(530, 390)
        preview.show()
        self.app.processEvents()
        venue = example(dateline=True)
        layer = VenueOverlay(preview, (venue,), self.folder)
        self.addCleanup(layer.close)
        layer._choose(venue)
        before = preview._screen_path(preview.venue_outline)[0]
        original = preview.venue_outline.copy()
        preview._set_center(preview._x+16, preview._y+5)
        after = preview._screen_path(preview.venue_outline)[0]
        self.assertLess((before-after-QPointF(16,5)).manhattanLength(), .001)
        preview.zoom(-1)
        line = preview._screen_path(original)
        mid = (line[0]+line[1])/2
        def edge_is_red():
            im = preview.grab().toImage()
            x, y = round(mid.x()*im.devicePixelRatio()), round(mid.y()*im.devicePixelRatio())
            pixels = [im.pixelColor(x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
            return any(p.red() > p.green()+70 and p.red() > p.blue()+60 for p in pixels)
        self.assertTrue(edge_is_red())
        layer._visible(False)
        self.assertFalse(edge_is_red())
        layer._visible(True)
        self.assertEqual(preview.venue_outline, original)
        self.assertEqual(preview.points, [])

    def test_saved_landmark_edits_update_both_views_and_survive_reopening(self):
        venue = example()
        with (patch("iosrealrun.venue_overlay.load_venues", return_value=(venue, Venue("待补"))),
              patch("iosrealrun.qt_desktop.read_settings", return_value=({}, RESOURCE_ROOT, ""))):
            window = Desktop(discover=False)
        self.addCleanup(window.close)
        window.venues.alignment_dir = self.folder
        window.show()
        editor = window.pick_route()
        self.addCleanup(editor.reject)
        self.app.processEvents()
        original = window.canvas.venue_outline.copy()
        original_route = window.display_points.copy()
        self.assertEqual(editor.canvas.venue_outline, original)
        dialog = editor.venues.open_alignment()
        self.app.processEvents()
        for index, point in enumerate(venue.base_locations()):
            dialog.selector.setCurrentIndex(index)
            screen = dialog.canvas._screen_path([point])[0]+QPointF(13, 7)
            QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=screen.toPoint())
        dialog.save_button.click()
        self.assertNotEqual(window.canvas.venue_outline, original)
        self.assertEqual(editor.canvas.venue_outline, window.canvas.venue_outline)
        self.assertEqual(window.display_points, original_route)
        saved = read_locations(venue, self.folder)
        self.assertEqual(Registration(venue.landmarks, saved).ring(venue), window.canvas.venue_outline)
        retry = editor.venues.open_alignment()
        retry.reset_positions()
        retry.reject()
        self.assertEqual(read_locations(venue, self.folder), saved)
        editor.venues.select_route("待补")
        self.assertFalse(editor.canvas.venue_outline)
        self.assertEqual(window.display_points, original_route)
