import os
import queue
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from iosrealrun.map_picker import MAX_ZOOM
from iosrealrun.qt_map_picker import open_map_picker


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

    def make_picker(self, *, load_tiles=False, closed=False):
        points = [{"lat": 30.26, "lng": 120.12}, {"lat": 30.27, "lng": 120.13}]
        dialog = open_map_picker(self.parent, points, self.results.append, closed=closed, load_tiles=load_tiles)
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
            picker = self.make_picker(load_tiles=True)
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
            picker = self.make_picker(load_tiles=True)
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


if __name__ == "__main__":
    unittest.main()
