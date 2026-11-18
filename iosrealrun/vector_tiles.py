"""Render OpenFreeMap vector tiles into the raster canvas on its worker threads."""

import json
import sqlite3
import threading
import time
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import mapbox_vector_tile
from google.protobuf.message import DecodeError
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from iosrealrun.map_picker import CACHE_BYTES, TILE_SIZE, USER_AGENT, WEEK, _TileLoader

TILEJSON = "https://tiles.openfreemap.org/planet"
MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Palette:
    land: str
    urban: str
    green: str
    sports: str
    water: str
    building: str
    outline: str
    road: str
    highway: str
    label: str


PALETTES = {
    "light": Palette("#f7f6f0", "#eeeee8", "#dce9d8", "#c4ddca", "#c5e0e9",
                     "#e3e0d8", "#cfcec5", "#ffffff", "#fff2cb", "#596665"),
    "street": Palette("#f7f2e7", "#ede9dc", "#c8e2b9", "#a8d5b1", "#9dcfde",
                      "#e1d7ca", "#c3b9ab", "#fffdf8", "#ffdb91", "#455c55"),
    "dark": Palette("#172a35", "#20323c", "#233f39", "#2e5348", "#173a50",
                    "#31424c", "#42545e", "#52636d", "#827969", "#cadbd9"),
}


def _read_url(url, limit):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urlopen(req, timeout=6) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Map response too large")
    if data.startswith(b"\x1f\x8b"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(data, limit + 1)
        if len(data) > limit or not decoder.eof:
            raise ValueError("Invalid compressed map response")
    return data


def _cached_bytes(db, url, ttl, limit):
    row = None
    if db is not None:
        db.execute("CREATE TABLE IF NOT EXISTS vector_cache (url TEXT PRIMARY KEY, saved REAL, data BLOB)")
        row = db.execute("SELECT saved, data FROM vector_cache WHERE url = ?", (url,)).fetchone()
    now = time.time()
    if row and now - row[0] < ttl:
        return row[1]
    try:
        data = _read_url(url, limit)
    except (OSError, HTTPException):
        if row:
            return row[1]
        raise
    if db is not None:
        with db:
            db.execute("INSERT OR REPLACE INTO vector_cache VALUES (?, ?, ?)", (url, now, data))
            db.execute("""DELETE FROM vector_cache WHERE url IN (
                SELECT url FROM (SELECT url, SUM(length(data)) OVER (ORDER BY saved DESC, url) AS bytes,
                    ROW_NUMBER() OVER (ORDER BY saved DESC, url) AS position FROM vector_cache)
                WHERE bytes > ? OR position > 1200)""", (CACHE_BYTES,))
    return data


def _tile_source(db):
    spec = json.loads(_cached_bytes(db, TILEJSON, 86400, 128 * 1024))
    template = spec["tiles"][0]
    if not template.startswith(TILEJSON + "/") or not template.endswith("/{z}/{x}/{y}.pbf"):
        raise ValueError("Unrecognized OpenFreeMap tile template")
    return template, min(14, max(0, int(spec["maxzoom"])))


def _parts(geometry):
    kind = geometry["type"]
    coords = geometry["coordinates"]
    if kind == "LineString":
        return [coords]
    if kind in ("MultiLineString", "Polygon"):
        return coords
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def _features(layers, layer_name):
    layer = layers.get(layer_name, {})
    scale = TILE_SIZE / layer.get("extent", 4096)
    for feat in layer.get("features", []):
        props = feat["properties"]
        geometry = feat["geometry"]
        path = QPainterPath()
        rings = geometry["type"] in ("Polygon", "MultiPolygon")
        for part in _parts(geometry):
            if len(part) < 2:
                continue
            x, y = part[0]
            path.moveTo(scale * x, scale * y)
            for x, y in part[1:]:
                path.lineTo(scale * x, scale * y)
            if rings:
                path.closeSubpath()
        if not path.isEmpty():
            yield props, path


GREENS = {"grass", "wood", "forest", "park", "garden", "meadow", "recreation_ground",
          "village_green", "cemetery", "farmland", "national_park", "nature_reserve"}
SPORTS = {"pitch", "sports_centre", "stadium", "golf_course", "playground", "track"}
MAJOR_ROADS = {"motorway", "trunk", "primary", "secondary"}


def _prepare(data):
    """Prepare immutable paths in parent-tile pixel coordinates once per source tile."""
    layers = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
    areas, roads, labels = [], [], []
    for layer in ("landcover", "landuse", "park", "water", "building"):
        for props, path in _features(layers, layer):
            category = props.get("class", "")
            if layer == "water":
                role = "water"
            elif layer == "building":
                role = "building"
            elif category in SPORTS:
                role = "sports"
            elif layer == "park" or category in GREENS:
                role = "green"
            elif layer == "landuse":
                role = "urban"
            else:
                continue
            areas.append((role, path, path.boundingRect()))
    for layer in ("waterway", "transportation"):
        for props, path in _features(layers, layer):
            kind = props.get("class", "")
            if layer == "waterway":
                role, width = "water", 1.3
            elif kind in MAJOR_ROADS:
                role, width = "highway", 3.0
            elif kind in ("rail", "transit", "path", "track"):
                role, width = "outline", 0.8
            else:
                role, width = "road", 1.8
            roads.append((role, width, path, path.boundingRect()))
    roads.sort(key=lambda road: road[1])
    for layer_name in ("place", "poi", "water_name", "transportation_name"):
        layer = layers.get(layer_name, {})
        scale = TILE_SIZE / layer.get("extent", 4096)
        for feat in layer.get("features", []):
            props = feat["properties"]
            name = props.get("name:zh-Hans") or props.get("name:zh") or props.get("name")
            if not isinstance(name, str) or not 0 < len(name) <= 48:
                continue
            geom = feat["geometry"]
            if geom["type"] == "Point":
                x, y = geom["coordinates"]
            elif geom["type"] == "LineString" and geom["coordinates"]:
                points = geom["coordinates"]
                x, y = points[len(points) // 2]
            else:
                continue
            labels.append((layer_name, name, QPointF(x * scale, y * scale)))
    return areas, roads, labels


def _render(scene, style, key, source_zoom):
    """Overzoom geometry before painting, so roads and labels remain crisp."""
    z, x, y = key
    factor = 2 ** (z - source_zoom)
    left, top = TILE_SIZE * (x % factor) / factor, TILE_SIZE * (y % factor) / factor
    view = QRectF(left, top, TILE_SIZE / factor, TILE_SIZE / factor)
    bounds = view.adjusted(-8 / factor, -8 / factor, 8 / factor, 8 / factor)
    palette = PALETTES[style]
    image = QImage(TILE_SIZE, TILE_SIZE, QImage.Format.Format_RGB32)
    image.fill(QColor(palette.land))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(factor, factor)
        painter.translate(-left, -top)
        areas, roads, labels = scene
        for role, path, rect in areas:
            if not bounds.intersects(rect):
                continue
            painter.fillPath(path, QColor(getattr(palette, role)))
            if role == "building" and z >= 15:
                painter.strokePath(path, QPen(QColor(palette.outline), 0.65 / factor))
        road_scale = min(5, max(0.48, 2 ** ((z - 14) * .45)))
        visible = [road for road in roads if bounds.intersects(road[3].adjusted(-.01, -.01, .01, .01))]
        for casing in (True, False):
            for role, width, path, rect in visible:
                if casing and role not in ("highway", "road"):
                    continue
                color = palette.outline if casing else getattr(palette, role)
                weight = width * road_scale + (1.2 if casing else 0)
                pen = QPen(QColor(color), weight / factor, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.strokePath(path, pen)
        painter.resetTransform()
        _draw_labels(painter, labels, view, factor, palette, z)
    finally:
        painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("Cannot encode rendered tile")
    return bytes(buffer.data())


def _draw_labels(painter, labels, view, factor, palette, zoom):
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"])
    font.setPixelSize(11)
    painter.setFont(font)
    metrics = QFontMetricsF(font)
    occupied = []
    frame = QRectF(2, 2, TILE_SIZE - 4, TILE_SIZE - 4)
    for layer, name, position in labels:
        if not view.contains(position) or (zoom < 15 and layer == "poi"):
            continue
        anchor = (position - view.topLeft()) * factor
        width = metrics.horizontalAdvance(name)
        baseline = QPointF(anchor.x() - width / 2, anchor.y() + metrics.ascent() / 2)
        box = QRectF(baseline.x() - 3, baseline.y() - metrics.ascent() - 2, width + 6, metrics.height() + 4)
        if not frame.contains(box) or any(box.intersects(other) for other in occupied):
            continue
        # Draw text through Qt's normal font fallback, including bitmap CJK glyphs.
        painter.setPen(QColor(palette.land))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(baseline + QPointF(dx, dy), name)
        painter.setPen(QColor(palette.label))
        painter.drawText(baseline, name)
        occupied.append(box)


class _VectorTileLoader(_TileLoader):
    """Share decoded source tiles across both windows, styles and overzoom levels."""

    _source_lock = threading.Lock()
    _source = None
    _source_until = 0.0
    _scenes = OrderedDict()

    def __init__(self, style):
        if style not in PALETTES:
            raise ValueError("Unknown vector map style")
        self.style = style
        super().__init__()

    def _scene(self, db, key):
        # Neighboring screen tiles very often come from the same parent. Serialize
        # parent fetch/decode, but render its children outside the lock.
        cls = type(self)
        with cls._source_lock:
            if self._closed or self.retry_delay:
                return None
            now = time.monotonic()
            if cls._source is None or now >= cls._source_until:
                cls._source = _tile_source(db)
                cls._source_until = now + 3600
            template, max_zoom = cls._source
            z, x, y = key
            parent_z = min(z, max_zoom)
            shift = z - parent_z
            url = template.format(z=parent_z, x=x >> shift, y=y >> shift)
            if url not in cls._scenes:
                cls._scenes[url] = _prepare(_cached_bytes(db, url, WEEK, MAX_BYTES))
                if len(cls._scenes) > 8:
                    cls._scenes.popitem(last=False)
            cls._scenes.move_to_end(url)
            return cls._scenes[url], parent_z

    def _fetch(self, db, key):
        try:
            loaded = self._scene(db, key)
            if loaded and not self._closed:
                scene, source_zoom = loaded
                return _render(scene, self.style, key, source_zoom)
        except HTTPError as exc:
            with exc:
                if exc.code in (403, 429, 503):
                    delay = (exc.headers or {}).get("Retry-After", "60")
                    self._back_off(max(60, int(delay)) if delay.isdecimal() else 60)
                elif exc.code != 404:
                    self._back_off(30)
        except (OSError, HTTPException, sqlite3.Error, DecodeError, ValueError, KeyError,
                TypeError, IndexError, OverflowError, zlib.error):
            self._back_off(30)
        return None
