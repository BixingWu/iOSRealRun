import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iosrealrun.desktop_routes import load_route, parse_route_text, read_last_route, route_length, save_last_route


from iosrealrun.paths import bundled_route


class DesktopRouteTests(unittest.TestCase):
    def test_bundled_route_loads(self):
        points, coordinate_system = load_route(bundled_route('ZJGEast.txt'))
        self.assertGreater(len(points), 2)
        self.assertIsNone(coordinate_system)
        self.assertIsInstance(points[0]['lat'], float)

    def test_json_removes_adjacent_duplicates_and_explicit_closure(self):
        points = parse_route_text('''[
            {"lat": 30, "lng": 120}, {"lat": "30", "lng": "120"},
            {"lat": 31, "lng": 121}, {"lat": 30, "lng": 120}, {"lat": 30, "lng": 120}
        ]''')
        self.assertEqual(points, [{'lat': 30.0, 'lng': 120.0}, {'lat': 31.0, 'lng': 121.0}])

    def test_legacy_paste_accepts_single_quotes_and_trailing_comma(self):
        points = parse_route_text("{'lat': 30, 'lng': 120}, {'lat': 31, 'lng': 121},")
        self.assertEqual(len(points), 2)

    def test_invalid_points_are_rejected(self):
        for point in (
            '{"lat": true, "lng": 120}', '{"lat": "nan", "lng": 120}',
            '{"lat": 30, "lng": Infinity}', '{"lat": 91, "lng": 120}',
            '{"lat": 30, "lng": -181}', '{"lng": 120}', '{"lat": 31, "lng": 121}',
        ):
            with self.subTest(point=point), self.assertRaises(ValueError):
                parse_route_text(f'[{point}, {{"lat": 31, "lng": 121}}]')

    def test_route_limits(self):
        with patch('iosrealrun.desktop_routes.MAX_ROUTE_BYTES', 16), self.assertRaisesRegex(ValueError, '2 MB'):
            parse_route_text('[{"lat": 30, "lng": 120}]')
        with patch('iosrealrun.desktop_routes.MAX_ROUTE_POINTS', 1), self.assertRaisesRegex(ValueError, '1 个'):
            parse_route_text('[{"lat": 30, "lng": 120}, {"lat": 31, "lng": 121}]')

    def test_bom_encoded_legacy_route_files(self):
        contents = '[{"lat": 30, "lng": 120}, {"lat": 31, "lng": 121}]'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'route.txt'
            for encoding in ('utf-8-sig', 'utf-16', 'utf-32'):
                with self.subTest(encoding=encoding):
                    path.write_bytes(contents.encode(encoding))
                    points, coordinate_system = load_route(path)
                    self.assertEqual(len(points), 2)
                    self.assertIsNone(coordinate_system)

    def test_gpx_uses_wgs84_and_does_not_join_disconnected_segments(self):
        segment = '<trkseg><trkpt lat="30" lon="120"/><trkpt lat="31" lon="121"/></trkseg>'
        with tempfile.TemporaryDirectory() as folder:
            route_path = Path(folder) / 'example.gpx'
            route_path.write_text(
                f'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk>{segment}</trk></gpx>',
                encoding='utf-8',
            )
            points, coordinate_system = load_route(route_path)
            self.assertEqual(coordinate_system, 'wgs84')
            self.assertEqual(points[0], {'lat': 30.0, 'lng': 120.0})

            route_path.write_text(f'<gpx><trk>{segment * 2}</trk></gpx>', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '连续'):
                load_route(route_path)

    def test_open_route_preserves_an_explicit_return_and_has_no_implicit_return(self):
        text = '[{"lat": 30, "lng": 120}, {"lat": 30, "lng": 120.001}, {"lat": 30, "lng": 120}]'
        points = parse_route_text(text, preserve_endpoint=True)
        self.assertEqual(points[0], points[-1])
        self.assertAlmostEqual(route_length(points, closed=False), route_length(points[:2], closed=True))
        self.assertLess(route_length(points[:2], closed=False), route_length(points[:2], closed=True))

    def test_last_route_restores_name_coordinates_and_closure(self):
        points = parse_route_text('[{"lat": 30, "lng": 120}, {"lat": 30.001, "lng": 120}]')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state' / 'last-route.json'
            self.assertIsNone(read_last_route(path))
            save_last_route(path, points, '地图路线', 'wgs84', False)
            self.assertEqual(read_last_route(path), (points, '地图路线', 'wgs84', False))
            path.write_text('[]', encoding='utf-8')
            self.assertIsNone(read_last_route(path))


if __name__ == '__main__':
    unittest.main()
