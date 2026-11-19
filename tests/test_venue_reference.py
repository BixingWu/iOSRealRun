import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from iosrealrun.paths import RESOURCE_ROOT
from iosrealrun.qt_desktop import Desktop
from iosrealrun.venue_reference import Venue, VenueComparison, load_venues


class VenueReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.file = self.folder / "two-fields.png"
        picture = QImage(60, 100, QImage.Format.Format_RGB32)
        picture.fill(0xff3a7cb4)
        self.assertTrue(picture.save(str(self.file)))

    def test_catalog_accepts_local_files_and_keeps_list_only_entries(self):
        extra = self.folder / "单独图片.png"
        extra.write_bytes(self.file.read_bytes())
        (self.folder / "index.json").write_text(json.dumps([
            {"title": "田径场", "image": self.file.name, "routes": ["东", "西"], "map_top": .25},
            {"title": "足球场", "image": "../other.png", "map_top": 2},
        ]), encoding="utf-8")
        self.assertEqual(load_venues(self.folder), (
            Venue("田径场", self.file, ("东", "西"), .25), Venue("足球场"), Venue("单独图片", extra)))
        (self.folder / "index.json").write_text("malformed", encoding="utf-8")
        self.assertEqual({venue.file for venue in load_venues(self.folder)}, {self.file, extra})
        self.assertFalse(load_venues(self.folder / "missing"))

    def test_preview_and_editor_share_a_reference_without_rewriting_points(self):
        catalog = (Venue("相邻两块田径场", self.file, ("紫金港东操场", "紫金港西操场"), .25),
                   Venue("独立足球场"))
        with (patch("iosrealrun.venue_reference.load_venues", return_value=catalog),
              patch("iosrealrun.qt_desktop.read_settings", return_value=({}, RESOURCE_ROOT, ""))):
            window = Desktop(discover=False, load_tiles=False)
        self.addCleanup(window.close)
        original = window.display_points.copy()
        comparison = window.comparison
        comparison.select_route("紫金港西操场")
        self.assertEqual(comparison.selector.currentText(), catalog[0].title)
        self.assertTrue(comparison.button.isChecked())
        self.assertEqual(comparison.image.picture.height(), 75)
        self.assertIn("未标定", comparison.caption.text())
        editor = window.pick_route()
        self.addCleanup(editor.reject)
        self.assertTrue(editor.comparison.button.isChecked())
        self.assertEqual(editor.comparison.selector.currentText(), catalog[0].title)
        editor.comparison.selector.setCurrentText("独立足球场")
        self.assertTrue(editor.comparison.image.picture.isNull())
        self.assertFalse(editor.comparison.enlarge_button.isEnabled())
        self.assertIn("待补", editor.comparison.image.message)
        editor.reject()
        self.assertEqual(comparison.selector.currentText(), catalog[0].title)
        self.assertEqual(window.display_points, original)
        comparison.select_route("其他路线")
        self.assertFalse(comparison.button.isChecked())
        self.assertEqual(comparison.selector.currentIndex(), -1)
        comparison.select_route("紫金港东操场")
        comparison.button.click()
        comparison.select_route("紫金港西操场")
        self.assertFalse(comparison.button.isChecked())

    def test_temporary_image_can_be_carried_into_an_empty_view(self):
        first = VenueComparison(QWidget(), ())
        other = VenueComparison(QWidget(), ())
        self.addCleanup(first.close)
        self.addCleanup(other.close)
        first.button.click()
        with patch("iosrealrun.venue_reference.QFileDialog.getOpenFileName", return_value=(str(self.file), "")):
            first.open_button.click()
        other.copy_view(first)
        self.assertTrue(other.button.isChecked())
        self.assertFalse(other.image.picture.isNull())
        self.file.write_bytes(b"broken image")
        first._show_reference()
        self.assertFalse(first.enlarge_button.isEnabled())
        self.assertIn("无法读取", first.image.message)
