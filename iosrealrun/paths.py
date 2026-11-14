"""Resolve application assets independently of the current working directory."""

import sys
from pathlib import Path


RESOURCE_ROOT = Path(sys._MEIPASS).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
BUNDLED_ROUTES = {
    "紫金港东操场": "ZJGEast.txt",
    "紫金港西操场": "ZJGWest.txt",
    "玉泉操场": "YuQuan.txt",
    "西溪操场": "XiXi.txt",
    "海宁操场": "HaiNing.txt",
}


def bundled_route(filename):
    return RESOURCE_ROOT / "routes" / filename


def config_directory():
    if not getattr(sys, "frozen", False):
        return RESOURCE_ROOT
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "iOSRealRun"
    return Path(sys.executable).resolve().parent


def resolve_route(value, config_dir):
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = config_dir / path
    if path.parent in (Path("."), Path("routes")) and not candidate.is_file():
        filename = "YuQuan.txt" if path.name == "YQ.txt" else path.name
        if filename in BUNDLED_ROUTES.values():
            return bundled_route(filename)
    return candidate
