import sqlite3
import struct
import unittest
import zlib
from email.message import Message
from io import BytesIO
from threading import Condition
from unittest.mock import patch
from urllib.error import HTTPError

from iosrealrun.map_picker import (
    TILE_SIZE,
    USER_AGENT,
    WEEK,
    _TileLoader,
    _cache_lifetime,
    _fit,
    _parse_center,
    _project,
    _route_pixels,
    _unproject,
    _valid_tile,
    _visible_tiles,
)


def _png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _png_tile(pixels, color=0, *, interlace=0, palette=b""):
    header = struct.pack(">IIBBBBB", TILE_SIZE, TILE_SIZE, 8, color, 0, 0, interlace)
    palette_chunk = _png_chunk(b"PLTE", palette) if palette else b""
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + palette_chunk
            + _png_chunk(b"IDAT", zlib.compress(pixels)) + _png_chunk(b"IEND", b""))


PIXELS = bytes((TILE_SIZE + 1) * TILE_SIZE)
TILE = _png_tile(PIXELS)


class _Response(BytesIO):
    headers = {}


class MapGeometryTests(unittest.TestCase):
    def test_projection_round_trip(self):
        for point in [{"lat": 30.2675, "lng": 120.1203}, {"lat": -45, "lng": -180}]:
            with self.subTest(point=point):
                actual = _unproject(*_project(point, 16), 16)
                self.assertAlmostEqual(actual["lat"], point["lat"])
                self.assertAlmostEqual(actual["lng"], point["lng"])

    def test_fit_spans_nearby_points_across_the_date_line(self):
        points = [{"lat": 10, "lng": 179.99}, {"lat": 10, "lng": -179.99}]
        zoom, x, y = _fit(points, 700, 500)
        center = _unproject(x, y, zoom)
        self.assertGreater(zoom, 10)
        self.assertAlmostEqual(abs(center["lng"]), 180)
        self.assertAlmostEqual(center["lat"], 10)

    def test_requests_are_limited_to_the_visible_viewport(self):
        tiles = _visible_tiles(3, 12, 12, 500, 500)
        self.assertTrue(tiles)
        self.assertIn((3, 7, 0), {key for key, _, _ in tiles})
        for (_, x, y), left, top in tiles:
            self.assertTrue(0 <= x < 8 and 0 <= y < 8)
            self.assertTrue(-TILE_SIZE < left < 500 and -TILE_SIZE < top < 500)

    def test_route_keeps_shortest_segments_when_view_is_opposite_the_date_line(self):
        points = [{"lat": 10, "lng": 179.99}, {"lat": 10, "lng": -179.99}]
        center_x, center_y = _project({"lat": 10, "lng": 0}, 3)
        route = _route_pixels(points, 3, center_x, center_y, 700, 500)
        self.assertLess(abs(route[1][0] - route[0][0]), 1)

    def test_fit_can_show_a_route_spanning_several_continents(self):
        route = [{"lat": 50, "lng": 170}, {"lat": -50, "lng": 50}, {"lat": -20, "lng": -65}]
        zoom, x, y = _fit(route, 550, 280)
        positions = _route_pixels(route, zoom, x, y, 550, 280)
        for left, top in positions:
            self.assertTrue(0 <= left <= 550 and 0 <= top <= 280)

    def test_center_input_accepts_fullwidth_comma_and_rejects_invalid_data(self):
        self.assertEqual(_parse_center("30.25， 120.14"), {"lat": 30.25, "lng": 120.14})
        for value in ("nan,1", "90,1", "1,181", "1,2,3", "foo"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _parse_center(value)


class MapCacheTests(unittest.TestCase):
    def setUp(self):
        self.loader = object.__new__(_TileLoader)
        self.loader._condition = Condition()
        self.loader._closed = False
        self.loader._network_retry = 0
        self.cache = sqlite3.connect(":memory:")
        self.addCleanup(self.cache.close)
        self.cache.execute("CREATE TABLE tile(z, x, y, data, expires, etag, modified, PRIMARY KEY(z, x, y))")

    def test_cache_lifetime_respects_headers(self):
        self.assertEqual(_cache_lifetime({}, 0), WEEK)
        self.assertEqual(_cache_lifetime({"Cache-Control": 'max-age="50"', "Age": "12"}, 0), 38)
        self.assertEqual(_cache_lifetime({"Cache-Control": "no-cache, max-age=200"}, 0), 0)
        self.assertIsNone(_cache_lifetime({"Cache-Control": "no-store"}, 0))

    def test_stale_tiles_are_conditionally_revalidated(self):
        headers = Message()
        headers["Cache-Control"] = "max-age=100"
        key = (3, 1, 2)
        self.cache.execute("INSERT INTO tile VALUES (?, ?, ?, ?, 0, 'test-etag', NULL)", (*key, TILE))
        error = HTTPError("https://tile.openstreetmap.org/3/1/2.png", 304, "Not Modified", headers, BytesIO())
        with patch("iosrealrun.map_picker.urlopen", side_effect=error) as fetch:
            self.assertEqual(self.loader._fetch(self.cache, key), TILE)
            request = fetch.call_args.args[0]
            self.assertEqual(request.get_header("User-agent"), USER_AGENT)
            self.assertEqual(request.get_header("If-none-match"), "test-etag")
            self.assertEqual(self.loader._fetch(self.cache, key), TILE)
            fetch.assert_called_once()

    def test_invalid_fresh_cache_is_replaced_without_using_its_etag(self):
        key = (3, 1, 2)
        # Flip an IDAT CRC byte and preserve both the dimensions and the valid IEND.
        bad_crc = TILE[:-13] + bytes([TILE[-13] ^ 1]) + TILE[-12:]
        for bad_tile in (b"truncated", bad_crc, _png_tile(PIXELS[:-1])):
            with self.subTest(tile_length=len(bad_tile)):
                self.cache.execute("INSERT OR REPLACE INTO tile VALUES (?, ?, ?, ?, 9999999999, 'old-etag', NULL)",
                                   (*key, bad_tile))
                with patch("iosrealrun.map_picker.urlopen", return_value=_Response(TILE)) as fetch:
                    self.assertEqual(self.loader._fetch(self.cache, key), TILE)
                    self.assertIsNone(fetch.call_args.args[0].get_header("If-none-match"))
                self.assertEqual(self.cache.execute("SELECT data FROM tile").fetchone()[0], TILE)

    def test_image_validation_accepts_indexed_and_adam7_tiles(self):
        palette = b"\x00\x00\x00\xff\xff\xff"
        self.assertTrue(_valid_tile(_png_tile(PIXELS, color=3, palette=palette)))
        adam7_data = bytes(sum((width + 1) * height for width, height in (
            (32, 32), (32, 32), (64, 32), (64, 64), (128, 64), (128, 128), (256, 128)
        )))
        self.assertTrue(_valid_tile(_png_tile(adam7_data, interlace=1)))

    def test_wrong_scanline_filter_or_decompressed_length_is_rejected(self):
        self.assertFalse(_valid_tile(_png_tile(bytes([5]) + PIXELS[1:])))
        self.assertFalse(_valid_tile(_png_tile(PIXELS + b"\x00")))
        self.assertFalse(_valid_tile(_png_tile(PIXELS[:-1])))

    def test_invalid_tile_response_is_not_cached(self):
        with patch("iosrealrun.map_picker.urlopen", return_value=_Response(_png_tile(PIXELS[:-1]))):
            self.assertIsNone(self.loader._fetch(self.cache, (3, 1, 2)))
        self.assertIsNone(self.cache.execute("SELECT data FROM tile").fetchone())

    def test_backoff_skips_network_but_allows_fresh_cache_hits(self):
        headers = Message()
        headers["Retry-After"] = "75"
        self.cache.execute("INSERT INTO tile VALUES (3, 1, 2, ?, 9999999999, NULL, NULL)", (TILE,))
        error = HTTPError("https://tile.openstreetmap.org/3/1/3.png", 429, "Busy", headers, BytesIO())
        with patch("iosrealrun.map_picker.urlopen", side_effect=error) as fetch:
            self.assertIsNone(self.loader._fetch(self.cache, (3, 1, 3)))
            self.assertGreater(self.loader.retry_delay, 70)
            self.assertIsNone(self.loader._fetch(self.cache, (3, 2, 2)))
            self.assertEqual(self.loader._fetch(self.cache, (3, 1, 2)), TILE)
            fetch.assert_called_once()

    def test_cache_prunes_rows_to_payload_budget(self):
        self.cache.execute("INSERT INTO tile VALUES (3, 1, 2, ?, 1, NULL, NULL)", (TILE,))
        with patch("iosrealrun.map_picker.CACHE_BYTES", len(TILE)), patch("iosrealrun.map_picker.urlopen", return_value=_Response(TILE)):
            self.assertEqual(self.loader._fetch(self.cache, (3, 2, 2)), TILE)
        self.assertEqual(self.cache.execute("SELECT x FROM tile").fetchall(), [(2,)])

    def test_closing_skips_network_for_unstarted_requests(self):
        self.loader._closed = True
        with patch("iosrealrun.map_picker.urlopen") as fetch:
            self.assertIsNone(self.loader._fetch(self.cache, (3, 2, 2)))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
