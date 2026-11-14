"""Map projection and bounded OpenStreetMap tile cache shared by the Qt picker."""

import math
import os
import queue
import sqlite3
import struct
import sys
import threading
import time
import zlib
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen



TILE_SIZE = 256
MIN_ZOOM = 0
MAX_ZOOM = 19
MAX_LATITUDE = 85.05112878
TILE_URL = "https://tile.openstreetmap.org/{}/{}/{}.png"
USER_AGENT = "iOSRealRun desktop map (+https://github.com/BixingWu/iOSRealRun-26)"
MAX_TILE_BYTES = 512 * 1024
CACHE_TILE_LIMIT = 3000
CACHE_BYTES = 64 * 1024 * 1024
TILE_WORKERS = 3
WEEK = 7 * 86400
DEFAULT_CENTER = {"lat": 30.2675, "lng": 120.1203}
BACKGROUND = "#f6f8fb"
LINE = "#e4eaf2"
BLUE = "#0065d1"
WHITE = "#ffffff"


def _project(point, zoom):
    size = TILE_SIZE * 2 ** zoom
    latitude = math.radians(max(-MAX_LATITUDE, min(MAX_LATITUDE, point["lat"])))
    x = (point["lng"] + 180) / 360 * size
    y = (1 - math.asinh(math.tan(latitude)) / math.pi) / 2 * size
    return x, max(0, min(size, y))


def _unproject(x, y, zoom):
    size = TILE_SIZE * 2 ** zoom
    x = x % size
    y = max(0, min(size, y))
    return {
        "lat": math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / size)))),
        "lng": x / size * 360 - 180,
    }


def _wrapped_delta(x, reference, size):
    return (x - reference + size / 2) % size - size / 2


def _fit(points, width, height):
    if not points:
        return 16, *_project(DEFAULT_CENTER, 16)
    positions = [_project(point, 0) for point in points]
    xs = sorted(x % TILE_SIZE for x, _ in positions)
    # Cut the globe through the largest gap, keeping the selected points together.
    after_gap = max(range(len(xs)), key=lambda index: (
        xs[index] + (TILE_SIZE if index == 0 else 0) - xs[index - 1]
    ))
    ys = [y for _, y in positions]
    left = xs[after_gap]
    right = xs[after_gap - 1] + (TILE_SIZE if after_gap else 0)
    top, bottom = min(ys), max(ys)
    scale = min(max(1, width - 144) / max(right - left, 1e-9),
                max(1, height - 144) / max(bottom - top, 1e-9))
    zoom = max(MIN_ZOOM, min(MAX_ZOOM, math.floor(math.log2(scale))))
    return zoom, ((left + right) / 2 % TILE_SIZE) * 2 ** zoom, (top + bottom) / 2 * 2 ** zoom


def _route_pixels(points, zoom, center_x, center_y, width, height):
    size = TILE_SIZE * 2 ** zoom
    positions = []
    previous_x = center_x
    for point in points:
        x, y = _project(point, zoom)
        previous_x += _wrapped_delta(x, previous_x, size)
        positions.append((previous_x - center_x + width / 2, y - center_y + height / 2))
    return positions


def _visible_tiles(zoom, center_x, center_y, width, height):
    left, top = center_x - width / 2, center_y - height / 2
    count = 2 ** zoom
    columns = range(math.floor(left / TILE_SIZE), math.ceil((left + width) / TILE_SIZE))
    rows = range(max(0, math.floor(top / TILE_SIZE)), min(count, math.ceil((top + height) / TILE_SIZE)))
    result = [((zoom, column % count, row), round(column * TILE_SIZE - left), round(row * TILE_SIZE - top))
              for row in rows for column in columns]
    return sorted(result, key=lambda item: ((item[1] + TILE_SIZE / 2 - width / 2) ** 2
                                            + (item[2] + TILE_SIZE / 2 - height / 2) ** 2))


def _cache_file():
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "iOSRealRun" / "map-tiles.sqlite3"


def _cache_lifetime(headers, now):
    directives = {key.strip().lower(): value.strip() for key, _, value in
                  (directive.partition("=") for directive in headers.get("Cache-Control", "").split(","))}
    if "no-store" in directives:
        return None
    if "no-cache" in directives:
        return 0
    try:
        return max(0, int(directives["max-age"].strip('"')) - int(headers.get("Age", 0)))
    except (KeyError, ValueError, TypeError):
        pass
    try:
        return max(0, parsedate_to_datetime(headers["Expires"]).timestamp() - now)
    except (KeyError, TypeError, ValueError, OverflowError):
        return WEEK


def _valid_tile(data):
    if not isinstance(data, bytes) or len(data) > MAX_TILE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    if data[8:16] != b"\x00\x00\x00\rIHDR" or len(data) < 33:
        return False
    width, height, depth, color, compression, filtering, interlace = struct.unpack_from(">IIBBBBB", data, 16)
    formats = {
        0: (1, (1, 2, 4, 8, 16)), 2: (3, (8, 16)), 3: (1, (1, 2, 4, 8)),
        4: (2, (8, 16)), 6: (4, (8, 16)),
    }
    channels, depths = formats.get(color, (0, ()))
    if (width != TILE_SIZE or height != TILE_SIZE or depth not in depths
            or compression or filtering or interlace not in (0, 1)):
        return False

    checked = memoryview(data)
    image = bytearray()
    seen_palette = False
    offset = 8
    while offset + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 8 + length
        if end + 4 > len(data) or zlib.crc32(checked[offset + 4:end]) != struct.unpack_from(">I", data, end)[0]:
            return False
        if kind == b"IEND":
            return (length == 0 and end + 4 == len(data) and bool(image) and (color != 3 or seen_palette)
                    and _valid_png_image(image, channels * depth, interlace))
        if kind == b"PLTE":
            if seen_palette or image or color in (0, 4) or not 0 < length <= 768 or length % 3:
                return False
            if color == 3 and length // 3 > 2 ** depth:
                return False
            seen_palette = True
        elif kind == b"IDAT":
            image.extend(checked[offset + 8:end])
        elif kind[0] & 0x20 == 0 and (kind != b"IHDR" or offset != 8):
            return False
        offset = end + 4
    return False


def _valid_png_image(image, bits_per_pixel, interlace):
    # Adam7 partitions the image into seven passes. Each scanline starts with a filter byte.
    passes = (
        ((32, 32), (32, 32), (64, 32), (64, 64), (128, 64), (128, 128), (256, 128))
        if interlace else ((TILE_SIZE, TILE_SIZE),)
    )
    scanlines = [((width * bits_per_pixel + 7) // 8 + 1, rows) for width, rows in passes]
    expected_bytes = sum(stride * rows for stride, rows in scanlines)
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(image, expected_bytes + 1)
    except zlib.error:
        return False
    if len(pixels) != expected_bytes or not decoder.eof or decoder.unused_data:
        return False

    offset = 0
    for stride, rows in scanlines:
        end = offset + stride * rows
        if any(value > 4 for value in pixels[offset:end:stride]):
            return False
        offset = end
    return True


def _parse_center(text):
    latitude, longitude = map(float, text.replace("，", ",").split(","))
    if not -MAX_LATITUDE <= latitude <= MAX_LATITUDE or not -180 <= longitude <= 180:
        raise ValueError("Coordinates fall outside the supported map bounds")
    return {"lat": latitude, "lng": longitude}


class _TileLoader:
    """Keep network and disk IO off the UI thread."""

    _network_slots = threading.BoundedSemaphore(TILE_WORKERS)

    def __init__(self):
        self.results = queue.SimpleQueue()
        self._condition = threading.Condition()
        self._pending = []
        self._active = set()
        self._closed = False
        self._network_retry = 0
        for _ in range(TILE_WORKERS):
            threading.Thread(target=self._run, daemon=True).start()

    def request(self, keys):
        with self._condition:
            if self._closed:
                return
            self._pending = list(dict.fromkeys(key for key in keys if key not in self._active))
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()

    @property
    def retry_delay(self):
        with self._condition:
            return max(0, self._network_retry - time.time())

    def _run(self):
        cache = None
        try:
            path = _cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            cache = sqlite3.connect(path, timeout=1)
            cache.execute("""CREATE TABLE IF NOT EXISTS tile (
                z INTEGER, x INTEGER, y INTEGER, data BLOB, expires REAL, etag TEXT, modified TEXT,
                PRIMARY KEY (z, x, y))""")
            cache.commit()
        except (OSError, sqlite3.Error):
            if cache is not None:
                cache.close()
            cache = None
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._closed or self._pending)
                    if self._closed:
                        return
                    key = self._pending.pop(0)
                    self._active.add(key)
                image = None
                try:
                    image = self._fetch(cache, key)
                finally:
                    with self._condition:
                        self._active.discard(key)
                        if not self._closed:
                            self.results.put((key, image))
        finally:
            if cache is not None:
                cache.close()

    def _fetch(self, cache, key):
        now = time.time()
        cached = None
        if cache is not None:
            try:
                cached = cache.execute(
                    "SELECT data, expires, etag, modified FROM tile WHERE z = ? AND x = ? AND y = ?", key
                ).fetchone()
            except sqlite3.Error:
                pass
        if cached and not _valid_tile(cached[0]):
            try:
                with cache:
                    cache.execute("DELETE FROM tile WHERE z = ? AND x = ? AND y = ?", key)
            except sqlite3.Error:
                pass
            cached = None
        if cached and cached[1] > now:
            return cached[0]
        # Avoid repeated download without the persistent cache expected by the tile provider.
        if cache is None:
            return None
        headers = {"User-Agent": USER_AGENT, "Accept": "image/png"}
        if cached and cached[2]:
            headers["If-None-Match"] = cached[2]
        if cached and cached[3]:
            headers["If-Modified-Since"] = cached[3]
        try:
            with self._network_slots:
                with self._condition:
                    if self._closed or self._network_retry > time.time():
                        return None
                with urlopen(Request(TILE_URL.format(*key), headers=headers), timeout=4) as response:
                    data = response.read(MAX_TILE_BYTES + 1)
                    cache_headers = response.headers
        except HTTPError as error:
            with error:
                if error.code != 304 or cached is None:
                    if error.code in (403, 429, 503):
                        try:
                            value = error.headers.get("Retry-After", "60") if error.headers else "60"
                            retry_after = int(value) if value.isdecimal() else (
                                parsedate_to_datetime(value).timestamp() - now
                            )
                        except (TypeError, ValueError, OverflowError):
                            retry_after = 60
                        self._back_off(max(60, retry_after))
                    return None
                data, cache_headers = cached[0], error.headers or {}
        except (OSError, HTTPException):
            self._back_off(30)
            return None
        if not _valid_tile(data):
            return None
        cache_lifetime = _cache_lifetime(cache_headers, now)
        try:
            with cache:
                if cache_lifetime is None:
                    cache.execute("DELETE FROM tile WHERE z = ? AND x = ? AND y = ?", key)
                else:
                    cache.execute(
                        "INSERT OR REPLACE INTO tile VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (*key, data, now + cache_lifetime, cache_headers.get("ETag") or (cached and cached[2]),
                         cache_headers.get("Last-Modified") or (cached and cached[3])),
                    )
                    cache.execute("""DELETE FROM tile WHERE rowid IN (
                        SELECT rowid FROM (
                            SELECT rowid, ROW_NUMBER() OVER ordered AS position,
                                   SUM(LENGTH(data)) OVER ordered AS bytes
                            FROM tile
                            WINDOW ordered AS (ORDER BY expires DESC, rowid DESC)
                        ) WHERE position > ? OR bytes > ?
                    )""", (CACHE_TILE_LIMIT, CACHE_BYTES))
        except sqlite3.Error:
            pass
        return data

    def _back_off(self, seconds):
        with self._condition:
            self._network_retry = max(self._network_retry, time.time() + seconds)
