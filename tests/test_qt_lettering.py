import json
import math
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF, QTransform
from PySide6.QtWidgets import QApplication

from iosrealrun.desktop_routes import read_last_route, save_last_route
from iosrealrun.qt_desktop import Desktop
from iosrealrun.qt_lettering import LetteringLap
from iosrealrun.route_drawing import LETTERING_STROKES, SHAPES


class LetteringLapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_closed_ink_returns_tangentially_inside_rotated_bounds(self):
        for kind, vertices in LETTERING_STROKES.items():
            with self.subTest(kind=kind):
                stroke = QPolygonF([QPointF(x * 100, y * 100) for x, y in vertices])
                path = LetteringLap(kind, 0).screen_path(stroke)
                self.assertFalse(path.isEmpty())
                self.assertEqual(path.pointAtPercent(0), path.pointAtPercent(1))
                self.assertTrue(stroke.boundingRect().adjusted(-.001, -.001, .001, .001).contains(path.boundingRect()))
                incoming = path.pointAtPercent(1) - path.pointAtPercent(.9999)
                outgoing = path.pointAtPercent(.0001) - path.pointAtPercent(0)
                self.assertGreater(QPointF.dotProduct(incoming, outgoing), 0)
                angle = .83
                moved = QTransform().translate(45, 89).rotateRadians(angle).scale(2, 2)
                projected = LetteringLap(kind, angle).screen_path(moved.map(stroke))
                expected = moved.map(path)
                for fraction in (0, .23, .63, .88, 1):
                    delta = projected.pointAtPercent(fraction) - expected.pointAtPercent(fraction)
                    self.assertLess(math.hypot(delta.x(), delta.y()), .001)

    def test_restore_explicit_metadata_and_older_template_names(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "last-route.json"
            points = [{"lat": 30.26, "lng": 120.12}, {"lat": 30.27, "lng": 120.13}]
            save_last_route(file, points, SHAPES["gem"], "wgs84", False, lettering=LetteringLap("gem", .23))
            saved = read_last_route(file, include_lettering=True)
            self.assertEqual(saved[:4], read_last_route(file))
            self.assertEqual(LetteringLap.from_saved(saved[4]), ("gem", .23))
            data = json.loads(file.read_text(encoding="utf-8"))
            del data["lettering_preview"]
            file.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(LetteringLap.from_saved(read_last_route(file, include_lettering=True)[4]), ("gem", None))
            save_last_route(file, points, SHAPES["gem"], "wgs84", False)
            self.assertIsNone(read_last_route(file, include_lettering=True)[4])
            for invalid in (("gem", float("nan")), ("gem", True), ("unknown", 0), {}, []):
                self.assertIsNone(LetteringLap.from_saved(invalid))

    def test_editor_and_desktop_loop_twice_with_original_route_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Desktop(discover=False, load_tiles=False, draft_dir=Path(directory))
            window.route_store = Path(directory) / "last-route.json"
            self.addCleanup(window.close)
            for kind in LETTERING_STROKES:
                with self.subTest(kind=kind):
                    picker = window.pick_route()
                    picker.shape_box.setCurrentIndex(picker.shape_box.findData(kind))
                    canvas = picker.canvas
                    center = QPointF(canvas.rect().center())
                    for sign in (-1, 1):
                        canvas.add_point(center + sign * QPointF(100, 60))
                    original = canvas.draft_route.copy()
                    self.assertNotEqual(original[0], original[-1])
                    for show in (True, False, True):
                        picker.lettering_lap_box.setChecked(show)
                        canvas._screen_geometry(original)
                        self.assertEqual(canvas._painted_lap is not None, show)
                        self.assertEqual(canvas.draft_route, original)
                    picker.apply_button.click()
                    self.assertEqual(window.route_lettering.kind, kind)
                    self.assertFalse(window.closed.isChecked())
                    self.assertEqual(read_last_route(window.route_store)[0], original)
                    window.preview_button.click()
                    preview = window.canvas
                    self.assertTrue(preview.previewing and preview.show_lettering_lap)
                    for zoom in (0, 1):
                        if zoom:
                            preview.zoom(zoom)
                        preview._geometry = preview._screen_geometry(preview.points)
                        path, closing = preview._geometry[:2]
                        preview.seek_preview(0)
                        first = preview._marker_position(path, closing)
                        preview.seek_preview(1)
                        self.assertEqual(first, preview._marker_position(path, closing))
                    preview._advance_preview()
                    self.assertEqual(preview.preview_lap, 2)
                    self.assertIn("第 2 圈", window.map_state.text())
                    window.preview_button.click()
                    self.assertEqual(window.display_points, original)
                    self.assertIsNone(preview._painted_lap)
            window.set_route(original, "手绘路线", "wgs84", False, remember=False)
            window.preview_button.click()
            self.assertFalse(window.canvas.show_lettering_lap)
            window.preview_button.click()
