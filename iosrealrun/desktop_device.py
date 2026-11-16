"""USB device discovery and Developer Mode location simulation for the desktop app."""

import asyncio
import math
import sys
from bisect import bisect_right
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass

from pymobiledevice3 import usbmux
from pymobiledevice3.dtx.exceptions import DTXNsError, DTXProtocolError
from pymobiledevice3.exceptions import (
    AlreadyMountedError,
    ChannelClosedError,
    ConnectionFailedToUsbmuxdError,
    ConnectionTerminatedError,
    DeveloperModeIsNotEnabledError,
    DeviceNotFoundError,
    FatalPairingError,
    MissingValueError,
    NoDeviceConnectedError,
    NotPairedError,
    NotTrustedError,
    PairingError,
    PasscodeRequiredError,
    PasswordRequiredError,
    PyMobileDevice3Exception,
    UserspaceTunnelUnavailableError,
    UserDeniedPairingError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.mobile_image_mounter import DeveloperDiskImageMounter
from pymobiledevice3.services.simulate_location import DtSimulateLocation

from iosrealrun.driver.connect import device_version
from iosrealrun.legacy_image import find_legacy_image, legacy_image_directory
from iosrealrun.run import dvt_location, geodistance, to_wgs84


DEVELOPER_MODE_HELP = "在设备的「设置 → 隐私与安全性 → 开发者模式」中开启，并按提示重启和确认。"
TRUST_HELP = "请解锁设备，并在设备上点按「信任」。"
MINIMUM_VERSION_HELP = "桌面版需要 iOS 或 iPadOS 14 及以上版本。"
UNSUPPORTED_TUNNEL_HELP = "iOS / iPadOS 17.0–17.3 暂不支持。此版本需要升级至 17.4 或更高版本。"
_DEVICE_FAILURES = (PyMobileDevice3Exception, OSError, EOFError, asyncio.TimeoutError, DTXNsError, DTXProtocolError)
_TRUST_FAILURES = (PairingError, FatalPairingError, NotPairedError, NotTrustedError)


class DeviceError(RuntimeError):
    """An actionable device error for the desktop app."""


@dataclass(frozen=True)
class Device:
    udid: str
    name: str
    version: str = ""
    developer_mode: bool | None = None
    issue: str | None = None
    needs_trust: bool = False

    @property
    def uses_legacy_location(self):
        version = device_version(self.version)
        return version is not None and (14, 0) <= version < (17, 0)

    @property
    def ready(self):
        version = device_version(self.version)
        if version is None or version < (14, 0) or (17, 0) <= version < (17, 4):
            return False
        return not self.issue and not self.needs_trust and (version < (16, 0) or self.developer_mode is True)


def _device_error(exc, action):
    if isinstance(exc, ConnectionFailedToUsbmuxdError):
        if sys.platform == "win32":
            return "无法访问 Apple USB 服务。请确认已安装 iTunes 或 Apple Devices。"
        if sys.platform.startswith("linux"):
            return "无法访问 USB 设备服务。请确认已安装并启动 usbmuxd，当前账户有权访问该服务。"
        return "无法访问系统 USB 设备服务。请重新连接设备，并确认系统能够识别它。"
    if isinstance(exc, (DeviceNotFoundError, NoDeviceConnectedError, ConnectionTerminatedError, ChannelClosedError, EOFError)):
        return "设备已断开。请重新连接数据线并解锁设备。"
    if isinstance(exc, (PasswordRequiredError, PasscodeRequiredError)):
        return "设备已锁定。请解锁设备后重试。"
    if isinstance(exc, UserDeniedPairingError):
        return "设备拒绝了信任请求。请重新连接设备，然后在设备上点按「信任」。"
    if isinstance(exc, _TRUST_FAILURES):
        return TRUST_HELP
    if isinstance(exc, DeveloperModeIsNotEnabledError):
        return DEVELOPER_MODE_HELP
    if isinstance(exc, UserspaceTunnelUnavailableError):
        return f"无法建立设备隧道。请重新连接已信任的 USB 设备。\n{exc}"
    if isinstance(exc, asyncio.TimeoutError):
        return f"{action}超时。请确认设备保持连接且已解锁。"
    detail = str(exc) or type(exc).__name__
    return f"{action}失败。请确认设备保持连接且已解锁。\n{detail}"


async def _describe_device(lockdown, udid):
    values = lockdown.all_values or {}
    name = values.get("DeviceName") or lockdown.display_name or "iPhone / iPad"
    raw_version = values.get("ProductVersion")
    version = raw_version.strip() if isinstance(raw_version, str) else ""
    if values.get("PasswordProtected"):
        return Device(udid, name, version, issue="设备已锁定。请解锁设备后刷新。")
    if not lockdown.paired:
        return Device(udid, name, version, issue=TRUST_HELP, needs_trust=True)
    if values.get("DeviceClass") not in (None, "iPhone", "iPad", "iPod"):
        return Device(udid, name, version, issue="此设备不支持 iPhone 或 iPad 定位回放。")
    version_number = device_version(version)
    if version_number is None:
        return Device(udid, name, version, issue="无法读取设备系统版本。请解锁设备后刷新。")
    if version_number < (14, 0):
        return Device(udid, name, version, issue=MINIMUM_VERSION_HELP)
    if (17, 0) <= version_number < (17, 4):
        return Device(udid, name, version, issue=UNSUPPORTED_TUNNEL_HELP)
    # Developer Mode was introduced in iOS 16. A missing toggle on iOS 14/15
    # is expected and must not prevent these devices from using the desktop.
    if version_number < (16, 0):
        return Device(udid, name, version)
    try:
        developer_mode = await asyncio.wait_for(lockdown.get_developer_mode_status(), 5)
    except (DeveloperModeIsNotEnabledError, MissingValueError):
        developer_mode = False
    except _DEVICE_FAILURES as exc:
        needs_trust = isinstance(exc, _TRUST_FAILURES) and not isinstance(exc, PasswordRequiredError)
        return Device(udid, name, version, issue=_device_error(exc, "读取开发者模式"), needs_trust=needs_trust)
    issue = None if developer_mode else DEVELOPER_MODE_HELP
    return Device(udid, name, version, developer_mode, issue)


async def _read_device(udid, *, pair=False):
    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=udid, connection_type="USB", autopair=pair, pair_timeout=20),
        25 if pair else 6,
    )
    async with lockdown:
        return await _describe_device(lockdown, udid)


async def list_devices():
    """Read attached USB devices without initiating a pairing request."""
    try:
        devices = await asyncio.wait_for(usbmux.list_devices(), 5)
    except _DEVICE_FAILURES as exc:
        raise DeviceError(_device_error(exc, "读取 USB 设备")) from exc

    async def read(udid):
        try:
            return await _read_device(udid)
        except _DEVICE_FAILURES as exc:
            needs_trust = isinstance(exc, _TRUST_FAILURES) and not isinstance(exc, PasswordRequiredError)
            return Device(udid, "iPhone / iPad", issue=_device_error(exc, "读取设备状态"), needs_trust=needs_trust)

    serials = dict.fromkeys(device.serial for device in devices if device.is_usb)
    return list(await asyncio.gather(*(read(udid) for udid in serials)))


async def connect_device(udid):
    """Request ordinary USB pairing, which requires the device's Trust confirmation."""
    try:
        return await _read_device(udid, pair=True)
    except _DEVICE_FAILURES as exc:
        raise DeviceError(_device_error(exc, "连接设备")) from exc


async def reveal_developer_mode(udid):
    """Ask an already trusted device to show its Developer Mode toggle in Settings."""
    try:
        lockdown = await asyncio.wait_for(
            create_using_usbmux(serial=udid, connection_type="USB", autopair=False), 6
        )
        async with lockdown:
            device = await _describe_device(lockdown, udid)
            if device.ready:
                return
            if device.developer_mode is None:
                raise DeviceError(device.issue)
            if not device.developer_mode:
                await asyncio.wait_for(AmfiService(lockdown).reveal_developer_mode_option_in_ui(), 6)
    except _DEVICE_FAILURES as exc:
        raise DeviceError(_device_error(exc, "显示开发者模式开关")) from exc


async def _clear_location(location):
    try:
        await asyncio.wait_for(location.clear(), 8)
    except _DEVICE_FAILURES as exc:
        detail = str(exc) or type(exc).__name__
        raise DeviceError(f"未能恢复设备定位。请重新连接设备后点击「恢复定位」。\n{detail}") from exc


class _ReplayStopped(Exception):
    """Replay was stopped while waiting for an operation."""


async def _open_location_service(stack, udid):
    device = await _read_device(udid)
    if device.issue:
        raise DeviceError(device.issue)

    if device.uses_legacy_location:
        return await _open_legacy_location_service(stack, device)

    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

    tunnel = UserspaceRsdTunnel(serial=udid, autopair=False, remotepairing_fallback=False)
    stack.push_async_callback(tunnel.aclose)
    rsd = await asyncio.wait_for(tunnel.aopen(), 20)
    if not rsd.udid or rsd.udid.replace("-", "").lower() != udid.replace("-", "").lower():
        raise DeviceError("隧道已连接的设备与所选设备不一致。请刷新设备列表后重试。")
    return await stack.enter_async_context(dvt_location(rsd))


async def _open_legacy_location_service(stack, device):
    lockdown = await asyncio.wait_for(
        create_using_usbmux(serial=device.udid, connection_type="USB", autopair=False), 6
    )
    await stack.enter_async_context(lockdown)
    # Recheck the live connection before mounting; the device can lock or lose
    # trust between discovery and pressing Start.
    current = await _describe_device(lockdown, device.udid)
    if not current.ready or not current.uses_legacy_location:
        raise DeviceError(current.issue or "设备状态已改变。请刷新设备列表后重试。")
    await _prepare_legacy_image(lockdown, current.version)
    # DtSimulateLocation opens and closes a fresh developer service for each
    # set/clear command. Keep its USB lockdown alive for the entire replay.
    return DtSimulateLocation(lockdown)


async def _prepare_legacy_image(lockdown, version):
    async with AsyncExitStack() as stack:
        mounter = DeveloperDiskImageMounter(lockdown)
        # Register cleanup before connecting so cancellation also closes a
        # partially opened mounter. The surrounding replay remains stoppable.
        stack.push_async_callback(mounter.close)
        if await asyncio.wait_for(mounter.is_image_mounted("Developer"), 8):
            return
        image = find_legacy_image(version)
        if image is None:
            directory = legacy_image_directory(version)
            raise DeviceError(
                f"未找到 iOS {version} 的开发者镜像。请将匹配的 DeveloperDiskImage.dmg "
                f"和 DeveloperDiskImage.dmg.signature 放入以下文件夹，再点击「开始模拟」：\n{directory}"
            )
        try:
            await asyncio.wait_for(mounter.mount(*image), 90)
        except AlreadyMountedError:
            # Another client may have mounted the image after our first check.
            pass
        except asyncio.TimeoutError as exc:
            raise DeviceError("准备开发者镜像超时。请保持设备解锁，重新连接后重试。") from exc


async def _wait_or_stop(operation, stop_requested):
    task = asyncio.create_task(operation)
    try:
        while not task.done():
            if stop_requested():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                raise _ReplayStopped
            await asyncio.wait((task,), timeout=0.05)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@asynccontextmanager
async def _location_service(udid, *, stop_requested=None):
    try:
        async with AsyncExitStack() as stack:
            opening = _open_location_service(stack, udid)
            if stop_requested is None:
                location = await opening
            else:
                try:
                    location = await _wait_or_stop(opening, stop_requested)
                except _ReplayStopped:
                    location = None
            yield location
    except _DEVICE_FAILURES as exc:
        raise DeviceError(_device_error(exc, "访问设备定位服务")) from exc


async def reset_location(udid):
    async with _location_service(udid) as location:
        await _clear_location(location)


def _prepare_segments(points, coordinate_system, *, closed):
    points = [to_wgs84(point, coordinate_system) for point in points]
    if closed and points:
        points.append(points[0])
    segments = []
    ends = []
    distance = 0.0
    for first, last in zip(points, points[1:]):
        length = geodistance(first, last)
        if length > 0:
            segments.append((first, last, distance, length))
            distance += length
            ends.append(distance)
    if not segments:
        raise ValueError("路线至少需要两个不同的坐标点。")
    return segments, ends


def _point_at_distance(segments, ends, distance):
    if distance >= ends[-1]:
        return segments[-1][1]
    first, last, start, length = segments[bisect_right(ends, distance)]
    fraction = (distance - start) / length
    if fraction == 0:
        return first
    longitude_delta = (last["lng"] - first["lng"] + 180) % 360 - 180
    longitude = (first["lng"] + fraction * longitude_delta + 180) % 360 - 180
    return {"lat": first["lat"] + fraction * (last["lat"] - first["lat"]), "lng": longitude}


async def _wait_until(clock, deadline, stop_requested, pause_requested):
    """Wait for the next sample while keeping paused time outside the replay clock."""
    paused_time = 0.0
    while not stop_requested():
        if pause_requested():
            before = clock()
            while pause_requested() and not stop_requested():
                await asyncio.sleep(0.05)
            paused = clock() - before
            paused_time += paused
            deadline += paused
        else:
            remaining = deadline - clock()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 0.05))
    return paused_time


async def replay_route(
    udid,
    points,
    *,
    speed,
    laps,
    interval,
    coordinate_system,
    stop_requested,
    pause_requested,
    on_progress,
    closed=True,
) -> bool:
    """Replay a route and report whether a location was sent and cleared.

    Closed routes return to the start at the end of each lap. Progress receives
    the lap, fraction and WGS84 point.
    """
    if not math.isfinite(speed) or speed <= 0 or not math.isfinite(interval) or interval <= 0:
        raise ValueError("速度和定位间隔必须是正数。")
    if not isinstance(laps, int) or laps < 0:
        raise ValueError("圈数必须是非负整数。")
    if stop_requested():
        return False

    segments, ends = _prepare_segments(points, coordinate_system, closed=closed)
    length = ends[-1]
    duration = length / speed
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("路线耗时超出可用范围。")
    if stop_requested():
        return False

    clock = asyncio.get_running_loop().time
    first_sample = interval if interval < duration else duration / 2
    async with _location_service(udid, stop_requested=stop_requested) as location:
        if location is None:
            return False
        attempted_location = False
        try:
            lap = 1
            while (laps == 0 or lap <= laps) and not stop_requested():
                started = clock()
                scheduled = 0.0
                while not stop_requested():
                    started += await _wait_until(clock, started + scheduled, stop_requested, pause_requested)
                    if stop_requested():
                        return attempted_location
                    elapsed = 0 if scheduled == 0 else min(duration, max(scheduled, clock() - started))
                    if scheduled == first_sample and elapsed >= duration:
                        # Preserve an intermediate sample even if the first write took a full lap.
                        elapsed = first_sample
                    fraction = elapsed / duration
                    point = _point_at_distance(segments, ends, fraction * length)
                    attempted_location = True
                    try:
                        await _wait_or_stop(
                            asyncio.wait_for(location.set(point["lat"], point["lng"]), 8), stop_requested
                        )
                    except _ReplayStopped:
                        return attempted_location
                    on_progress(lap, fraction, point)
                    if fraction >= 1:
                        break
                    scheduled = first_sample if scheduled == 0 else min(duration, elapsed + interval)
                lap += 1
        finally:
            if attempted_location:
                await _clear_location(location)
        return attempted_location
