import argparse
import asyncio
import logging
import math
import os
import sys
from pathlib import Path

import coloredlogs
from yaml import YAMLError
from pymobiledevice3.dtx.exceptions import DTXNsError, DTXProtocolError
from pymobiledevice3.exceptions import PyMobileDevice3Exception

import config
import run
from desktop_routes import load_route, route_length
from driver.connect import device_version
from init import init, tunnel


logger = logging.getLogger(__name__)


def configure_logging():
    level = logging.DEBUG if os.environ.get("DEBUG") else logging.INFO
    coloredlogs.install(level=level)
    for name in ("wintun", "quic", "asyncio", "zeroconf", "parso", "humanfriendly", "blib2to3", "urllib3"):
        logging.getLogger(name).setLevel(logging.DEBUG if level == logging.DEBUG else logging.WARNING)


async def mount_legacy_image(serial):
    logger.info("正在挂载旧版设备所需的开发者磁盘镜像…")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pymobiledevice3", "mounter", "auto-mount", "--udid", serial
    )
    try:
        if await process.wait() != 0:
            raise RuntimeError(
                "开发者磁盘镜像挂载失败。请检查设备连接、信任状态和开发者模式。"
                "如果已手动挂载，请使用 --skip-mount 重试。"
            )
    finally:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()


async def main(skip_mount=False):
    settings = config.Config()
    path = Path(settings.routeConfig)
    points, source_system = load_route(path)
    speed = float(settings.v)
    interval = float(getattr(settings, "updateInterval", 0.2))
    coordinate_system = source_system or getattr(settings, "coordinateSystem", "bd09")
    if not 0.1 <= speed <= 30 or not 0.1 <= interval <= 10:
        raise ValueError("速度需为 0.1–30 m/s，定位间隔需为 0.1–10 秒。")
    distance = route_length([run.to_wgs84(point, coordinate_system) for point in points])
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("路线长度需大于零。")
    # The legacy sampler materializes one lap and varies speed by up to 2×.
    raw_distance = route_length(points)
    samples_per_lap = max(distance, raw_distance) / speed / interval
    if samples_per_lap > 125_000:
        raise ValueError("单圈定位点太多。请选择更短的路线、提高速度或增大定位间隔。")

    version, serial = await init.init(include_serial=True)
    version_number = device_version(version)
    if version_number is None:
        raise RuntimeError("无法读取设备系统版本。请解锁并重新连接设备。")
    if (17, 0) <= version_number < (17, 4):
        raise RuntimeError("命令行的 USB 隧道需要 iOS 或 iPadOS 17.4 及以上版本。")
    if version_number < (17, 0) and not skip_mount:
        await mount_legacy_image(serial)

    logger.info("路线 %s · 每圈 %.1f 米 · %s · 更新间隔 %.2f 秒", path.name, distance, coordinate_system, interval)
    print(f"将以约 {speed:g} m/s 循环回放路线。按 Ctrl+C 停止并尝试恢复定位。")
    options = {"update_interval": interval, "coordinate_system": coordinate_system, "clear_on_finish": True}
    if version_number >= (17, 4):
        async with tunnel.tunnel(serial) as (address, port):
            await run.run(address, port, points, speed, **options)
    else:
        await run.run_legacy(points, speed, serial=serial, **options)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="iOSRealRun 路线模拟")
    parser.add_argument("--skip-mount", action="store_true", help="跳过 iOS 17 以下设备的开发者磁盘镜像挂载")
    args = parser.parse_args()
    configure_logging()
    try:
        asyncio.run(main(skip_mount=args.skip_mount))
    except KeyboardInterrupt:
        print("回放已停止。")
    except (PyMobileDevice3Exception, DTXNsError, DTXProtocolError, YAMLError,
            OSError, EOFError, ValueError, TypeError, AttributeError, ArithmeticError, RuntimeError) as error:
        logger.error("%s", str(error) or type(error).__name__)
        raise SystemExit(1) from None
