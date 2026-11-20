import math
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QWidget

from iosrealrun.drawing_drafts import draft_catalog, load_draft
from iosrealrun.map_picker import MAX_ZOOM, _route_pixels
from iosrealrun.qt_map_picker import MapPreview, open_map_picker


class _TileLoader:
    retry_delay = 0

    def __init__(self):
        self.results = queue.SimpleQueue()
        self.requests = []
        self.closed = False

    def request(self, keys):
        self.requests.append(tuple(keys))

    def close(self):
        self.closed = True


class QtMapPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.parent.show()
        self.addCleanup(self.parent.close)
        self.results = []

    def make_picker(self, *, load_tiles=False, closed=False, style="light"):
        points = [{"lat": 30.26, "lng": 120.12}, {"lat": 30.27, "lng": 120.13}]
        dialog = open_map_picker(self.parent, points, self.results.append, closed=closed, load_tiles=load_tiles,
                                 style=style)
        self.app.processEvents()
        return dialog

    def test_modal_draft_starts_empty_and_apply_emits_new_points(self):
        picker = self.make_picker(closed=True)
        canvas = picker.canvas
        center = canvas.rect().center()
        self.assertEqual(picker.windowModality(), Qt.WindowModality.WindowModal)
        self.assertTrue(picker.isVisible())
        self.assertFalse(picker.apply_button.isEnabled())
        self.assertFalse(picker.undo_button.isEnabled())
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center + QPoint(85, 48))
        self.assertEqual(len(canvas.points), 2)
        self.assertTrue(picker.apply_button.isEnabled())
        self.assertFalse(canvas.grab().isNull())
        QTest.mouseClick(picker.apply_button, Qt.MouseButton.LeftButton)
        self.assertFalse(picker.isVisible())
        self.assertEqual(len(self.results), 1)
        self.assertEqual(len(self.results[0]), 2)
        self.assertTrue(all(30.2 < point["lat"] < 30.4 for point in self.results[0]))

    def test_drag_does_not_add_a_point_while_undo_and_clear_update_actions(self):
        picker = self.make_picker()
        canvas = picker.canvas
        source = canvas.rect().center()
        target = source + QPoint(90, 36)
        original_center = canvas._x, canvas._y
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseMove(canvas, target)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(canvas.points, [])
        self.assertNotEqual((canvas._x, canvas._y), original_center)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=source)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
        QTest.mouseClick(picker.undo_button, Qt.MouseButton.LeftButton)
        self.assertEqual(len(canvas.points), 1)
        self.assertFalse(picker.apply_button.isEnabled())
        QTest.mouseClick(picker.clear_button, Qt.MouseButton.LeftButton)
        self.assertEqual(canvas.points, [])
        self.assertFalse(picker.undo_button.isEnabled())
        QTest.keyClick(picker, Qt.Key.Key_Escape)
        self.assertFalse(picker.isVisible())
        self.assertEqual(self.results, [])

    def test_smoothing_and_templates_preserve_the_hand_drawn_anchors(self):
        picker = self.make_picker()
        canvas = picker.canvas
        center = canvas.rect().center()
        for delta in (QPoint(-80, -30), QPoint(80, -30), QPoint(80, 60)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center + delta)
        anchors = canvas.points.copy()
        draft = canvas.draft_route.copy()
        self.assertGreater(len(draft), len(anchors))
        picker.smooth_box.click()
        self.assertEqual(canvas.draft_route, anchors)
        picker.smooth_box.click()
        self.assertEqual(canvas.draft_route, draft)

        picker.shape_box.setCurrentIndex(picker.shape_box.findData("ikun"))
        self.assertFalse(picker.apply_button.isEnabled())
        for delta in (QPoint(-70, -30), QPoint(80, 40)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center + delta)
        self.assertTrue(picker.apply_button.isEnabled())
        lettering = canvas.draft_route.copy()
        self.assertFalse(canvas.route_closed)
        self.assertTrue(picker.direction_box.isVisible())
        picker.direction_box.setCurrentIndex(picker.direction_box.findData("vertical"))
        self.assertNotEqual(canvas.draft_route, lettering)
        picker.direction_box.setCurrentIndex(picker.direction_box.findData("auto"))
        self.assertEqual(canvas.draft_route, lettering)
        picker.shape_box.setCurrentIndex(picker.shape_box.findData("heart"))
        self.assertFalse(picker.direction_box.isVisible())
        self.assertTrue(canvas.route_closed)
        self.assertNotEqual(canvas.draft_route, lettering)
        picker.shape_box.setCurrentIndex(0)
        self.assertEqual(canvas.draft_route, draft)
        picker.shape_box.setCurrentIndex(picker.shape_box.findData("ikun"))
        self.assertEqual(canvas.draft_route, lettering)
        picker.apply_button.click()
        self.assertEqual(self.results, [lettering])

    def test_shape_handles_move_scale_rotate_and_undo_across_the_date_line(self):
        picker = self.make_picker()
        canvas = picker.canvas
        canvas.center_on({"lat": 30, "lng": 179.9998})
        picker.shape_box.setCurrentIndex(picker.shape_box.findData("ikun"))
        center = QPointF(canvas.rect().center())
        for offset in (QPointF(-54, -32), QPointF(54, 32)):
            canvas.add_point(center + offset)
        original = canvas.corners.copy()
        self.assertGreater(original[0]["lng"], 0)
        self.assertLess(original[1]["lng"], 0)
        viewport = canvas._x, canvas._y

        def drag(pos, destination):
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos.toPoint())
            QTest.mouseMove(canvas, destination.toPoint())
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=destination.toPoint())

        handles = canvas._placement_handles()
        move = QPointF(17, 13)
        drag(handles["move"], handles["move"] + move)
        self.assertEqual((canvas._x, canvas._y), viewport)
        self.assertLess((canvas._placement_handles()["move"] - handles["move"] - move).manhattanLength(), .01)
        shifted = canvas.corners.copy()
        handles = canvas._placement_handles()
        drag(handles[2], handles[0] + (handles[2] - handles[0]) * 1.5)
        scaled = canvas._placement_handles()
        self.assertLess((scaled[0] - handles[0]).manhattanLength(), .01)
        for edge in (1, 3):
            ratio = (scaled[edge] - scaled[0]).manhattanLength() / (handles[edge] - handles[0]).manhattanLength()
            self.assertAlmostEqual(ratio, 1.5, places=2)
        before_rotate = canvas.corners.copy()
        arm = scaled["rotate"] - scaled["move"]
        drag(scaled["rotate"], scaled["move"] + QPointF(-arm.y(), arm.x()))
        rotated = canvas._placement_handles()
        self.assertAlmostEqual(canvas.rotation, math.pi / 2, places=2)
        self.assertLess((rotated["move"] - scaled["move"]).manhattanLength(), .01)
        for edge in (1, 3):
            before, after = scaled[edge] - scaled[0], rotated[edge] - rotated[0]
            self.assertAlmostEqual(math.hypot(*before.toTuple()), math.hypot(*after.toTuple()), places=4)
        for corners in (before_rotate, shifted, original):
            picker.undo_button.click()
            self.assertEqual(canvas.corners, corners)
        self.assertEqual(canvas.rotation, 0)
        picker.reject()

    def test_draft_dialogs_reopen_original_anchors_and_template_in_a_new_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            picker = self.make_picker()
            picker.draft_dir = directory
            canvas = picker.canvas
            center = QPointF(canvas.rect().center())
            canvas.add_point(center)
            picker.hand_closed_box.click()
            picker.smooth_box.click()
            picker.shape_box.setCurrentIndex(picker.shape_box.findData("ikun"))
            picker.direction_box.setCurrentIndex(picker.direction_box.findData("vertical"))
            canvas.add_point(center - QPointF(80, 35))
            canvas.add_point(center + QPointF(80, 35))
            canvas.rotation = .31
            canvas._draft_changed()
            picker.reference_box.click()
            expected = canvas.points.copy(), canvas.corners.copy(), canvas.draft_route.copy(), canvas.reference.copy()
            save = picker.save_draft_dialog()
            for field in save.findChildren(QLineEdit):
                field.setText("操场 A" if field.accessibleName() == "场地" else "字样草图")
            next(b for b in save.findChildren(QPushButton) if b.text() == "保存").click()
            identifier = picker.draft_id
            picker.store_drawing("操场 A", "字样草图")
            self.assertEqual(picker.draft_id, identifier)
            picker.store_drawing("操场 A", "另一份")
            picker.store_drawing("操场 B", "字样草图")
            self.assertEqual(len(draft_catalog(directory)), 3)
            picker.reject()

            fresh = self.make_picker()
            fresh.draft_dir = directory
            library = fresh.open_draft_dialog()
            boxes = {box.accessibleName(): box for box in library.findChildren(QComboBox)}
            boxes["草稿场地"].setCurrentText("操场 A")
            boxes["已有草稿"].setCurrentIndex(boxes["已有草稿"].findData(identifier))
            next(b for b in library.findChildren(QPushButton) if b.text() == "打开").click()
            self.assertEqual(fresh.draft_id, identifier)
            self.assertEqual(fresh.direction_box.currentData(), "vertical")
            self.assertFalse(fresh.reference_box.isChecked())
            self.assertEqual(fresh.canvas.rotation, .31)
            self.assertEqual((fresh.canvas.points, fresh.canvas.corners, fresh.canvas.draft_route, fresh.canvas.reference),
                             expected)
            fresh.shape_box.setCurrentIndex(0)
            self.assertTrue(fresh.hand_closed_box.isChecked())
            self.assertFalse(fresh.smooth_box.isChecked())
            self.assertEqual(fresh.canvas.controls, expected[0])
            fresh.store_drawing("操场 A", "单点手绘")
            self.assertEqual(load_draft(directory, fresh.draft_id).points, expected[0])
            (directory / ("a" * 32 + ".json")).write_text("{}", encoding="utf-8")
            self.assertEqual(len(draft_catalog(directory)), 4)
            with self.assertRaises(ValueError):
                fresh.restore_drawing("../outside")
            fresh.reject()

    def test_location_input_validates_coordinates_and_keeps_draft(self):
        picker = self.make_picker()
        canvas = picker.canvas
        canvas.add_point(QPointF(canvas.rect().center()))
        QTest.mouseClick(picker.go_button, Qt.MouseButton.LeftButton)
        picker.coordinate_input.setText("99, 120.1")
        QTest.keyClick(picker.coordinate_input, Qt.Key.Key_Return)
        self.assertTrue(picker.coordinate_error.isVisible())
        picker.coordinate_input.setText("40.71，-74.01")
        QTest.keyClick(picker.coordinate_input, Qt.Key.Key_Return)
        self.assertFalse(picker.coordinate_panel.isVisible())
        self.assertEqual(len(canvas.points), 1)
        canvas.add_point(QPointF(canvas.width() / 2, canvas.height() / 2))
        self.assertEqual(canvas.points[-1], {"lat": 40.71, "lng": -74.01})
        picker.reject()

    def test_wheel_zoom_keeps_coordinate_under_cursor(self):
        picker = self.make_picker()
        canvas = picker.canvas
        anchor = QPointF(canvas.rect().center() + QPoint(70, -33))
        canvas.add_point(anchor)
        before = canvas.points[-1]
        zoom = canvas._zoom
        event = QWheelEvent(anchor, QPointF(canvas.mapToGlobal(anchor.toPoint())), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(canvas, event)
        self.assertEqual(canvas._zoom, min(zoom + 1, MAX_ZOOM))
        canvas.clear()
        canvas.add_point(anchor)
        self.assertEqual(canvas.points, [before])
        picker.reject()

    def test_offline_tiles_keep_drawing_available_and_closing_stops_loader(self):
        loader = _TileLoader()
        with patch("iosrealrun.qt_map_picker._TileLoader", return_value=loader):
            picker = self.make_picker(load_tiles=True, style="osm")
        canvas = picker.canvas
        canvas._debounce.stop()
        canvas._request()
        self.assertTrue(loader.requests[-1])
        visible = set(loader.requests[-1])
        self.assertEqual(visible, {key for key, _, _ in canvas._visible})
        for key in visible:
            loader.results.put((key, None))
        canvas._poll()
        self.assertEqual(canvas.status(), "底图暂不可用")
        self.assertTrue(canvas._retry_timer.isActive())
        canvas.add_point(QPointF(canvas.rect().center()))
        canvas.add_point(QPointF(canvas.rect().center() + QPoint(100, 70)))
        self.assertTrue(picker.apply_button.isEnabled())
        picker.close()
        self.assertTrue(loader.closed)
        self.assertFalse(canvas._retry_timer.isActive())
        self.assertFalse(canvas._poll_timer.isActive())

    def test_tile_pixmap_is_decoded_on_gui_thread(self):
        loader = _TileLoader()
        with patch("iosrealrun.qt_map_picker._TileLoader", return_value=loader):
            picker = self.make_picker(load_tiles=True, style="osm")
        canvas = picker.canvas
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        tile = QPixmap(256, 256)
        tile.fill(QColor("#b6d7b7"))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(tile.save(buffer, "PNG"))
        key = canvas._visible[0][0]
        loader.results.put((key, bytes(data)))
        canvas._poll()
        self.assertEqual(canvas._images[key].toImage().pixelColor(0, 0), QColor("#b6d7b7"))
        picker.reject()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_changing_style_preserves_draft_and_drops_previous_loader(self):
        loader = _TileLoader()
        with patch("iosrealrun.qt_map_picker._TileLoader", return_value=loader):
            picker = self.make_picker(load_tiles=True, style="osm")
        picker.canvas.add_point(QPointF(picker.canvas.rect().center()))
        original = list(picker.canvas.points)
        viewport = picker.canvas._x, picker.canvas._y, picker.canvas._zoom
        styles = []
        picker.mapStyleChanged.connect(styles.append)
        picker.style_box.setCurrentIndex(picker.style_box.findData("plain"))
        self.assertTrue(loader.closed)
        self.assertIsNone(picker.canvas._loader)
        self.assertFalse(picker.canvas._attribution.isVisible())
        self.assertEqual(original, picker.canvas.points)
        self.assertEqual(viewport, (picker.canvas._x, picker.canvas._y, picker.canvas._zoom))
        self.assertEqual(styles, ["plain"])
        picker.close()

    def test_replay_is_read_only_and_marker_tracks_geography_after_pan_and_zoom(self):
        preview = MapPreview(load_tiles=False, style="plain")
        self.addCleanup(preview.close)
        preview.resize(660, 350)
        preview.show()
        points = [{"lat": 30, "lng": 179.9995}, {"lat": 30.0005, "lng": -179.9995}]
        preview.set_route(points, False)
        self.app.processEvents()
        center = preview.rect().center()
        QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=center)
        QTest.keyClick(preview, Qt.Key.Key_Space)
        self.assertEqual(preview.points, points)
        QTest.keyClick(preview, Qt.Key.Key_Right)
        preview.zoom(-1)
        initial_view = preview._x, preview._y, preview._zoom
        for point in points:
            preview.set_marker(point)
            x, y = _route_pixels([point], preview._zoom, preview._x, preview._y, preview.width(), preview.height())[0]
            snapshot = preview.grab()
            dpr = snapshot.devicePixelRatio()
            self.assertEqual(snapshot.toImage().pixelColor(round(x * dpr), round(y * dpr)), QColor("#ef9c28"))
        self.assertEqual(initial_view, (preview._x, preview._y, preview._zoom))
        preview.set_marker(None)
        self.assertIsNone(preview.marker)


if __name__ == "__main__":
    unittest.main()
