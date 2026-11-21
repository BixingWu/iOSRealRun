import math
import unittest
from itertools import pairwise

from iosrealrun.desktop_routes import MAX_ROUTE_POINTS
from iosrealrun.map_picker import _project, _unproject
from iosrealrun.route_drawing import SHAPES, shape_layout, shape_route, smooth_route, track_angle
from iosrealrun.run import geodistance


class RouteDrawingTests(unittest.TestCase):
    def track_point(self, u, v, angle, lng=120):
        cx, cy = _project({"lat": 30, "lng": lng}, 19)
        c, s = math.cos(angle), math.sin(angle)
        return _unproject(cx + u * c - v * s, cy + u * s + v * c, 19)

    def test_track_angle_is_stable_with_uneven_sampling_reversal_and_wrapping(self):
        corners = [(-140, -42), (140, -42), (140, 42), (-140, 42), (-140, -42)]
        dense = corners[:1] + [(i, -42) for i in range(-139, 140)] + corners[1:]
        for degrees in (-32, 0, 35, 78, 90, 113):
            angle = math.radians(degrees)
            for ring in (corners, dense, dense[::-1], corners[:-1] + [(-140, -38)]):
                points = [self.track_point(u, v, angle, 179.99998) for u, v in ring]
                with self.subTest(degrees=degrees, start=ring[0], length=len(ring)):
                    self.assertAlmostEqual(track_angle(points), angle, places=6)
        for points in ([], [corners[0]], corners[:3], [(0, 0), (30, 0), (50, 0), (0, 0)],
                       [(-30, -30), (30, -30), (30, 30), (-30, 30), (-30, -30)]):
            self.assertIsNone(track_angle([self.track_point(u, v, .37) for u, v in points]))

    def test_letters_and_selection_share_the_tracks_rotated_frame(self):
        angle = math.radians(72)
        corners = [self.track_point(-160, -40, angle), self.track_point(160, 40, angle)]
        route, frame = shape_layout("ikun", corners, field_angle=angle)
        cx, cy = _project({"lat": 30, "lng": 120}, 19)

        def offsets(point):
            x, y = _project(point, 19)
            dx, dy = x - cx, y - cy
            return dx * math.cos(angle) + dy * math.sin(angle), dy * math.cos(angle) - dx * math.sin(angle)

        for point, (u, v) in zip(frame, ((-160, -40), (160, -40), (160, 40), (-160, 40)), strict=True):
            along, across = offsets(point)
            self.assertAlmostEqual(along, u, places=5)
            self.assertAlmostEqual(across, v, places=5)
        baseline, height = zip(*(offsets(point) for point in route))
        self.assertGreater(baseline[-1] - baseline[0], 305)
        self.assertGreater(max(height) - min(height), 72)
        self.assertTrue(all(abs(u) < 160 and abs(v) < 40 for u, v in zip(baseline, height)))
        reversed_route, _ = shape_layout("ikun", corners[::-1], field_angle=angle)
        for a, b in zip(route, reversed_route, strict=True):
            self.assertAlmostEqual(a["lng"], b["lng"], places=9)
            self.assertAlmostEqual(a["lat"], b["lat"], places=9)
        for mode in ("horizontal", "vertical"):
            self.assertEqual(shape_layout("ikun", corners, lettering_direction=mode, field_angle=angle),
                             shape_layout("ikun", corners, lettering_direction=mode))
        self.assertEqual(shape_layout("oval", corners, field_angle=angle), shape_layout("oval", corners))

    def test_hand_drawn_corner_is_rounded_and_evenly_spaced(self):
        a = {"lat": 30.0, "lng": 120.0}
        bend = {"lat": 30.0, "lng": 120.001}
        b = {"lat": 30.001, "lng": 120.001}
        route = smooth_route([a, bend, b])
        self.assertEqual((route[0], route[-1]), (a, b))
        self.assertGreater(len(route), 60)
        self.assertGreater(min(geodistance(p, bend) for p in route), 2)
        spans = [geodistance(x, y) for x, y in pairwise(route)]
        self.assertTrue(all(2.7 < span < 3.05 for span in spans))
        self.assertEqual(smooth_route([a, b]), [a, b])

    def test_closed_path_wraps_at_dateline_and_long_routes_are_bounded(self):
        near = [{"lat": 30, "lng": 179.9998}, {"lat": 30, "lng": -179.9998},
                {"lat": 30.0004, "lng": -179.9998}]
        route = smooth_route(near + near[:1], closed=True)
        self.assertTrue(all(abs(p["lng"]) > 179.99 for p in route))
        self.assertGreater(geodistance(route[0], route[-1]), .5)
        self.assertLess(geodistance(route[0], route[-1]), 3.1)
        long = smooth_route([near[0], {"lat": 10, "lng": 85}, near[-1]])
        self.assertEqual(len(long), MAX_ROUTE_POINTS)

    def test_shapes_fit_both_orientations_and_reversed_corners(self):
        a = {"lat": 30, "lng": 120}
        for b in ({"lat": 30.001, "lng": 120.002}, {"lat": 30.002, "lng": 120.001}):
            for kind in SHAPES:
                with self.subTest(kind=kind, b=b):
                    route = shape_route(kind, [a, b])
                    self.assertEqual(route, shape_route(kind, [b, a]))
                    self.assertGreaterEqual(len(route), 96)
                    self.assertTrue(all(a["lat"] < p["lat"] < b["lat"] and
                                        a["lng"] < p["lng"] < b["lng"] for p in route))
                    distance = geodistance(route[0], route[-1])
                    if kind in ("ikun", "gem"):
                        self.assertGreater(distance, 10)
                    else:
                        self.assertLess(distance, 3.1)
        self.assertEqual(shape_route("ikun", [a]), [])
        self.assertEqual(shape_route("heart", [a, a]), [])
        self.assertEqual(shape_route("heart", [a, {"lat": 30.1, "lng": 120}]), [])

    def test_templates_use_the_short_side_of_the_dateline(self):
        corners = [{"lat": 30, "lng": 179.9995}, {"lat": 30.001, "lng": -179.9995}]
        route = shape_route("eight", corners)
        self.assertTrue(route)
        self.assertTrue(all(math.isfinite(p["lat"]) and abs(p["lng"]) > 179.9995 for p in route))

    def test_gem_is_one_open_stroke_in_the_tracks_frame(self):
        angle = math.radians(70)
        corners = [self.track_point(-240, -75, angle), self.track_point(240, 75, angle)]
        gem, frame = shape_layout("gem", corners, field_angle=angle)
        ikun, expected_frame = shape_layout("ikun", corners, field_angle=angle)
        self.assertEqual(frame, expected_frame)
        self.assertNotEqual(gem, ikun)
        self.assertNotEqual(gem, shape_route("gem", corners, lettering_direction="horizontal", field_angle=angle))
        self.assertLess(max(geodistance(a, b) for a, b in pairwise(gem)), 3.05)
        self.assertGreater(geodistance(gem[0], gem[-1]), 50)

    def test_beamed_notes_keep_their_proportions_in_wide_and_tall_boxes(self):
        for width, height in ((280, 90), (90, 280)):
            corners = [self.track_point(-width, -height, 0), self.track_point(width, height, 0)]
            notes = shape_route("notes", corners)
            xs, ys = zip(*(_project(point, 19) for point in notes))
            aspect = (max(xs) - min(xs)) / (max(ys) - min(ys))
            self.assertTrue(1.1 < aspect < 1.25, aspect)
            self.assertLess(max(geodistance(a, b) for a, b in pairwise(notes + notes[:1])), 3.05)

    def test_large_letters_fill_the_box_and_allow_explicit_orientation(self):
        box = [{"lat": 30, "lng": 120}, {"lat": 30.0015, "lng": 120.001}]
        auto = shape_route("ikun", box)
        horizontal = shape_route("ikun", box, lettering_direction="horizontal")
        vertical = shape_route("ikun", box, lettering_direction="vertical")
        self.assertEqual(auto, vertical)
        self.assertNotEqual(horizontal, vertical)
        for key in ("lat", "lng"):
            coords = [point[key] for point in vertical]
            low, high = box[0][key], box[1][key]
            self.assertGreater((max(coords) - min(coords)) / (high - low), .92)
            self.assertTrue(all(low < value < high for value in coords))
        self.assertGreater(horizontal[-1]["lng"] - horizontal[0]["lng"], .0008)
        self.assertGreater(vertical[0]["lat"] - vertical[-1]["lat"], .0013)
