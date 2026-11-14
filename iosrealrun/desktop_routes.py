import ast
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree


MAX_ROUTE_BYTES = 2 * 1024 * 1024
MAX_ROUTE_POINTS = 20_000


def _normalize_points(points, *, preserve_endpoint=False) -> list[dict[str, float]]:
    if not isinstance(points, (list, tuple)):
        raise ValueError("请输入带有 lat 和 lng 的坐标列表。")
    if len(points) > MAX_ROUTE_POINTS:
        raise ValueError(f"路线最多支持 {MAX_ROUTE_POINTS:,} 个坐标点。")

    result = []
    for index, point in enumerate(points, 1):
        try:
            latitude = point['lat']
            longitude = point['lng']
            if isinstance(latitude, bool) or isinstance(longitude, bool):
                raise ValueError
            latitude = float(latitude)
            longitude = float(longitude)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"第 {index} 个坐标点需要有效的 lat 和 lng。") from error

        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError(f"第 {index} 个坐标点的纬度必须在 -90 到 90 之间。")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError(f"第 {index} 个坐标点的经度必须在 -180 到 180 之间。")

        normalized = {'lat': latitude, 'lng': longitude}
        if not result or normalized != result[-1]:
            result.append(normalized)

    # The run loop adds its own return leg, so a repeated starting point is redundant.
    if not preserve_endpoint and len(result) > 1 and result[0] == result[-1]:
        result.pop()
    if len(result) < 2:
        raise ValueError("路线至少需要两个不同的坐标点。")
    return result


def parse_route_text(text: str, *, preserve_endpoint=False) -> list[dict[str, float]]:
    if len(text) > MAX_ROUTE_BYTES:
        raise ValueError("路线内容不能超过 2 MB。")
    try:
        byte_count = len(text.encode('utf-8'))
    except UnicodeEncodeError as error:
        raise ValueError("路线含有无效的 Unicode 文本。") from error
    if byte_count > MAX_ROUTE_BYTES:
        raise ValueError("路线内容不能超过 2 MB。")
    text = text.strip().lstrip('\ufeff').strip()
    if not text.startswith(('[', '{')):
        raise ValueError("请输入带有 lat 和 lng 的 JSON 坐标。")

    if text.startswith('{'):
        text = f'[{text}]'
    try:
        points = json.loads(text)
    except (ValueError, RecursionError):
        try:
            # Existing route files also accept Python literal syntax, such as single quotes.
            points = ast.literal_eval(text)
        except (SyntaxError, ValueError, RecursionError) as error:
            raise ValueError("无法解析路线。请检查 JSON 坐标格式。") from error

    return _normalize_points(points, preserve_endpoint=preserve_endpoint)


def _parse_gpx(text: str, *, preserve_endpoint=False) -> list[dict[str, float]]:
    if '<!DOCTYPE' in text or '<!ENTITY' in text:
        raise ValueError("GPX 文件不能包含 XML 文档类型或实体声明。")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValueError("无法解析 GPX 文件。") from error
    if root.tag.rsplit('}', 1)[-1] != 'gpx':
        raise ValueError("请选择有效的 GPX 文件。")

    segments = [segment.findall('{*}trkpt') for segment in root.findall('{*}trk/{*}trkseg')]
    routes = [route.findall('{*}rtept') for route in root.findall('{*}rte')]
    paths = [points for points in segments + routes if points]
    if len(paths) != 1:
        raise ValueError("GPX 文件需要包含一条连续的轨迹或路线。")
    return _normalize_points([
        {'lat': point.get('lat'), 'lng': point.get('lon')} for point in paths[0]
    ], preserve_endpoint=preserve_endpoint)


def load_route(path: str | Path, *, preserve_endpoint=False) -> tuple[list[dict[str, float]], str | None]:
    path = Path(path)
    with path.open('rb') as file:
        data = file.read(MAX_ROUTE_BYTES + 1)
    if len(data) > MAX_ROUTE_BYTES:
        raise ValueError("路线文件不能超过 2 MB。")
    try:
        if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
            text = data.decode('utf-32')
        elif data.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = data.decode('utf-16')
        else:
            text = data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError("请将路线文件保存为 UTF-8 编码。") from error
    if path.suffix.lower() == '.gpx':
        return _parse_gpx(text, preserve_endpoint=preserve_endpoint), 'wgs84'
    return parse_route_text(text, preserve_endpoint=preserve_endpoint), None


def route_length(points: list[dict[str, float]], *, closed: bool = True) -> float:
    from iosrealrun.run import geodistance

    if len(points) < 2:
        return 0
    length = sum(geodistance(first, last) for first, last in zip(points, points[1:]))
    return length + geodistance(points[-1], points[0]) if closed else length


def last_route_path() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        folder = Path(os.environ["LOCALAPPDATA"]) / "iOSRealRun"
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "iOSRealRun"
    else:
        folder = Path.home() / ".local" / "state" / "iosrealrun"
    return folder / "last-route.json"


def read_last_route(path: Path):
    try:
        with path.open("rb") as file:
            data = file.read(MAX_ROUTE_BYTES + 1)
        if len(data) > MAX_ROUTE_BYTES:
            return None
        saved = json.loads(data)
        name, points, system, closed = (saved[key] for key in ("name", "points", "system", "closed"))
        if (not isinstance(name, str) or not name.strip() or len(name) > 1024
                or system not in ("bd09", "gcj02", "wgs84")
                or not isinstance(closed, bool) or not isinstance(points, list)):
            return None
        return _normalize_points(points, preserve_endpoint=True), name, system, closed
    except (OSError, TypeError, KeyError, ValueError, RecursionError):
        return None


def save_last_route(path: Path, points, name, system, closed):
    data = json.dumps({"name": name, "points": points, "system": system, "closed": closed},
                      ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_ROUTE_BYTES:
        raise ValueError("路线太大，无法保存。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
