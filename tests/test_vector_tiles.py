import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mapbox_vector_tile
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from iosrealrun.vector_tiles import PALETTES, TILEJSON, _VectorTileLoader, _prepare, _render


class VectorTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # A lake wholly inside the southeast child; vector coordinates grow down.
        cls.tile = mapbox_vector_tile.encode({
            "name": "water",
            "features": [{"geometry": "POLYGON ((2450 2450, 3800 2450, 3800 3800, 2450 3800, 2450 2450))",
                          "properties": {}}],
        }, default_options={"y_coord_down": True})

    def test_overzoom_preserves_geography_in_all_styles(self):
        scene = _prepare(self.tile)
        for style, palette in PALETTES.items():
            with self.subTest(style=style):
                southeast = QImage.fromData(_render(scene, style, (15, 1, 1), 14))
                northwest = QImage.fromData(_render(scene, style, (15, 0, 0), 14))
                self.assertEqual(southeast.pixelColor(128, 128), QColor(palette.water))
                self.assertEqual(northwest.pixelColor(128, 128), QColor(palette.land))

    def test_neighboring_screen_tiles_fetch_only_one_dated_parent(self):
        from collections import OrderedDict

        template = TILEJSON + "/test/{z}/{x}/{y}.pbf"
        with (
            patch.object(_VectorTileLoader, "_source", None),
            patch.object(_VectorTileLoader, "_scenes", OrderedDict()),
            patch("iosrealrun.vector_tiles._tile_source", return_value=(template, 14)),
            patch("iosrealrun.vector_tiles._cached_bytes", return_value=self.tile) as fetch,
            patch("iosrealrun.map_picker.threading.Thread.start"),
        ):
            first = _VectorTileLoader("light")
            second = _VectorTileLoader("dark")
            self.assertTrue(first._fetch(None, (16, 40, 80)))
            self.assertTrue(second._fetch(None, (16, 41, 81)))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args.args[1], template.format(z=14, x=10, y=20))
