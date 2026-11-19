import math
import unittest
from itertools import pairwise

from iosrealrun.desktop_routes import MAX_ROUTE_POINTS
from iosrealrun.route_drawing import SHAPES, shape_route, smooth_route
from iosrealrun.run import geodistance


class RouteDrawingTests(unittest.TestCase):
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
                    if kind == "ikun":
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
