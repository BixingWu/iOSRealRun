"""Register a local venue outline to WGS 84 using matching map landmarks."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from iosrealrun.desktop_routes import MAX_ROUTE_BYTES, last_route_path, write_route_json
from iosrealrun.map_picker import MAX_LATITUDE, TILE_SIZE, _project, _unproject, _wrapped_delta
from iosrealrun.paths import config_directory


def _pair(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 2 or
            not all(type(v) in (float, int) and math.isfinite(v) for v in value)):
        raise ValueError("坐标必须是两个有限数值。")
    return tuple(value)


def _location(value):
    if value is None:
        return None
    lng, lat = _pair(value)
    if not (-180 <= lng <= 180 and -MAX_LATITUDE <= lat <= MAX_LATITUDE):
        raise ValueError("地标超出了底图的经纬度范围。")
    return {"lng": lng, "lat": lat}


@dataclass(frozen=True)
class Landmark:
    name: str
    pixel: tuple
    location: dict | None


@dataclass(frozen=True)
class Venue:
    title: str
    routes: tuple = ()
    outline: tuple = ()
    landmarks: tuple = ()
    center: dict | None = None
    credit: str = ""

    def base_locations(self):
        return [mark.location for mark in self.landmarks]


def load_venues(directory=None):
    folder = Path(directory) if directory is not None else config_directory() / "场地参考"
    venues = {}
    for filename in ("index.json", "boundaries.json"):
        try:
            with (folder / filename).open("rb") as file:
                payload = file.read(MAX_ROUTE_BYTES + 1)
            if len(payload) > MAX_ROUTE_BYTES:
                continue
            records = json.loads(payload)
        except (OSError, ValueError, RecursionError):
            continue
        for row in records if isinstance(records, list) else ():
            if not isinstance(row, dict) or not isinstance(row.get("title"), str) or not row["title"].strip():
                continue
            title = row["title"].strip()
            aliases = row.get("routes", venues.get(title, Venue(title)).routes)
            routes = tuple(a for a in aliases if isinstance(a, str)) if isinstance(aliases, (list, tuple)) else ()
            try:
                outline = tuple(_pair(p) for p in row.get("outline", []))
                landmarks = tuple(Landmark(m["name"], _pair(m["pixel"]), _location(m.get("wgs84")))
                                  for m in row.get("landmarks", []))
                if (any(not isinstance(m.name, str) or not m.name.strip() for m in landmarks)
                        or len(outline) > 4096 or len(landmarks) > 100):
                    raise ValueError
                credit = row.get("credit", "")
                venues[title] = Venue(title, routes, outline, landmarks, _location(row.get("center")),
                                      credit if isinstance(credit, str) else "")
            except (ValueError, KeyError, TypeError, OverflowError):
                venues.setdefault(title, Venue(title, routes))
    return tuple(venues.values())


class Registration:
    """Least-squares translation, rotation and uniform scale in Web Mercator."""

    def __init__(self, landmarks, locations):
        pairs = [(complex(*mark.pixel), loc) for mark, loc in zip(landmarks, locations, strict=True) if loc]
        if len(pairs) < 3:
            raise ValueError("至少需要三个已对齐的地标。")
        source, points = zip(*pairs)
        reference_x = _project(points[0], 0)[0]
        world = [complex(reference_x + _wrapped_delta(x, reference_x, TILE_SIZE), y)
                 for x, y in (_project(p, 0) for p in points)]
        self.origin = sum(source) / len(source)
        self.target = sum(world) / len(world)
        centered = [s - self.origin for s in source]
        longest = max(centered, key=abs)
        if not longest or max(abs((s * longest.conjugate()).imag) for s in centered) < abs(longest)**2 * .001:
            raise ValueError("请选择分散在场地不同方向的地标。")
        scale = sum(abs(s)**2 for s in centered)
        self.factor = sum(s.conjugate() * (w - self.target) for s, w in zip(centered, world)) / scale
        spread = max(abs(w - self.target) for w in world)
        axis = max(world, key=lambda w: abs(w - self.target)) - self.target
        if (not self.factor or not spread or
                max(abs(((w - self.target) * axis.conjugate()).imag) for w in world) < spread**2 * .001):
            raise ValueError("底图上的地标位置需要分散且互不重合。")
        residual = sum(abs(self.target + self.factor * s - w)**2 for s, w in zip(centered, world))
        latitude = sum(p["lat"] for p in points) / len(points)
        self.rms_metres = math.sqrt(residual / len(world)) * 40075016.68558 * math.cos(math.radians(latitude)) / TILE_SIZE

    def project(self, pixel):
        point = self.target + (complex(*pixel) - self.origin) * self.factor
        return _unproject(point.real, point.imag, 0)

    def ring(self, venue):
        return [self.project(p) for p in venue.outline]


def alignment_path(venue, directory=None):
    data = [venue.title, venue.outline, [(m.name, m.pixel, m.location) for m in venue.landmarks]]
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    directory = last_route_path().parent / "venue-alignments" if directory is None else directory
    return directory / (fingerprint + ".json")


def read_locations(venue, directory=None):
    try:
        with alignment_path(venue, directory).open("rb") as file:
            raw = file.read(32769)
        if len(raw) <= 32768:
            values = json.loads(raw)
            if isinstance(values, list) and len(values) == len(venue.landmarks):
                locations = [_location(v) for v in values]
                Registration(venue.landmarks, locations)
                return locations
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        pass
    return venue.base_locations()


def save_locations(venue, locations, directory=None):
    Registration(venue.landmarks, locations)
    values = [[p["lng"], p["lat"]] if p else None for p in locations]
    write_route_json(alignment_path(venue, directory), values, 32768)
