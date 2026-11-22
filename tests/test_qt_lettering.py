import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF, QTransform
from PySide6.QtWidgets import QApplication

from iosrealrun.desktop_routes import read_last_route, save_last_route
from iosrealrun.qt_desktop import Desktop
from iosrealrun.qt_lettering import LetteringLap
from iosrealrun.route_drawing import LETTERING_STROKES, SHAPES, shape_route


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

    def test_lettering_preview_leaves_a_reprojectable_trail_at_the_displayed_speed(self):
        window = Desktop(discover=False, load_tiles=False)
        self.addCleanup(window.close)
        canvas = window.canvas
        box = [{"lat": 45, "lng": -70}, {"lat": 45.001, "lng": -69.998}]
        with patch.object(window, "submit", side_effect=AssertionError("unexpected device operation")):
            for kind in LETTERING_STROKES:
                with self.subTest(kind=kind):
                    points = shape_route(kind, box, lettering_direction="horizontal")
                    window.set_route(points, SHAPES[kind], "wgs84", False, remember=False,
                                     lettering=LetteringLap(kind, 0))
                    window.preview_button.click()
                    canvas._random.seed(27)
                    canvas.seek_preview(.35)
                    speeds = []
                    for _ in range(80):
                        previous_fraction, previous_speed = canvas.preview_fraction, canvas.preview_speed
                        with patch("iosrealrun.qt_map_picker.time.monotonic", return_value=canvas._last_tick + .15):
                            canvas._advance_preview()
                        average_speed = (previous_speed + canvas.preview_speed) / 2
                        expected = previous_fraction + .15 * average_speed / canvas.preview_length
                        self.assertAlmostEqual(canvas.preview_fraction, expected)
                        speeds.append(canvas.preview_speed)
                    self.assertLess(min(speeds), 5)
                    self.assertGreater(max(speeds), 5)
                    self.assertTrue(all(4.85 - 1e-9 <= speed <= 5.15 + 1e-9 for speed in speeds))
                    self.assertIn(f"{canvas.preview_speed:.2f} 米/秒", window.map_state.text())
                    minutes, seconds = divmod(round(1000 / canvas.preview_speed), 60)
                    self.assertEqual(window.pace_text.text(), f"{minutes}:{seconds:02d} /km")
                    self.assertEqual(window.pace_caption.text(), "预演配速")
                    history = list(canvas._preview_trail)
                    self.assertEqual(len(history), canvas._preview_trail.maxlen)
                    self.assertGreater(len({offset.toTuple() for _, offset in history}), 1)
                    for zoom in (0, -1):
                        if zoom:
                            canvas.zoom(zoom)
                        canvas._geometry = canvas._screen_geometry(canvas.points)
                        line = canvas._preview_line(*canvas._geometry[:2])
                        self.assertEqual(list(canvas._preview_trail), history)
                        displacements = []
                        for fraction, offset in history:
                            centre = line.pointAtPercent(line.percentAtLength(line.length() * fraction))
                            delta = canvas._preview_position(line, fraction, offset) - centre
                            displacements.append(math.hypot(delta.x(), delta.y()))
                        self.assertGreater(max(displacements), .2)
                        self.assertLessEqual(max(displacements), 3.000001)
                        fraction = 1 - 1e-7
                        centre = line.pointAtPercent(line.percentAtLength(line.length() * fraction))
                        near_seam = canvas._preview_position(line, fraction, QPointF(3, 0)) - centre
                        self.assertLess(near_seam.manhattanLength(), .01)
                    canvas.seek_preview(1)
                    self.assertFalse(canvas._preview_trail)
                    canvas._advance_preview()
                    self.assertEqual(canvas.preview_lap, 2)
                    window.preview_button.click()
                    self.assertFalse(canvas._preview_trail)
                    self.assertEqual(window.pace_text.text(), "3:20 /km")
                    self.assertEqual(window.pace_caption.text(), "配速")
                    self.assertEqual(window.display_points, points)

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
