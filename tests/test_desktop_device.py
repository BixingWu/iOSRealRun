import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pymobiledevice3.exceptions import ConnectionFailedToUsbmuxdError, MissingValueError, NotPairedError

from iosrealrun.desktop_device import Device, DeviceError, _describe_device, list_devices, replay_route, reset_location
from iosrealrun.run import dvt_location


class DesktopDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_usb_service_has_platform_specific_help(self):
        for platform, hint in (("linux", "usbmuxd"), ("win32", "Apple Devices"), ("darwin", "系统 USB")):
            with (
                self.subTest(platform=platform),
                patch("iosrealrun.desktop_device.sys.platform", platform),
                patch("iosrealrun.desktop_device.usbmux.list_devices", AsyncMock(side_effect=ConnectionFailedToUsbmuxdError)),
            ):
                with self.assertRaisesRegex(DeviceError, hint):
                    await list_devices()

    async def test_usb_listing_filters_network_entries_and_preserves_devices_with_errors(self):
        attached = [
            SimpleNamespace(serial="first", is_usb=True),
            SimpleNamespace(serial="first", is_usb=True),
            SimpleNamespace(serial="second", is_usb=True),
            SimpleNamespace(serial="network", is_usb=False),
        ]
        ready = Device("first", "iPad", "26.4", True)
        with (
            patch("iosrealrun.desktop_device.usbmux.list_devices", AsyncMock(return_value=attached)),
            patch("iosrealrun.desktop_device._read_device", AsyncMock(side_effect=[ready, TimeoutError()])),
        ):
            first, second = await list_devices()
        self.assertEqual(first, ready)
        self.assertEqual(second.udid, "second")
        self.assertIn("超时", second.issue)

    async def test_unpaired_device_keeps_reported_version_and_requests_trust(self):
        attached = [SimpleNamespace(serial=udid, is_usb=True) for udid in ("first", "second")]

        unpaired = MagicMock(all_values={"DeviceName": "iPad", "ProductVersion": "27.0"}, paired=False)
        with (
            patch("iosrealrun.desktop_device.usbmux.list_devices", AsyncMock(return_value=attached)),
            patch("iosrealrun.desktop_device.create_using_usbmux", AsyncMock(side_effect=[unpaired, NotPairedError()])),
        ):
            first, second = await list_devices()
        self.assertEqual(first.version, "27.0")
        self.assertTrue(first.needs_trust)
        self.assertTrue(second.needs_trust)

    async def test_device_discovery_distinguishes_version_and_family(self):
        for version, family, expected_issue in (
            ("13.7", "iPhone", "需要 iOS"),
            ("17.3.1", "iPhone", "17.0–17.3 暂不支持"),
            ("iOS?", "iPhone", "无法读取设备系统版本"),
            ("26.5", "AppleTV", "此设备不支持"),
            ("26.5", "iPad", None),
            ("27.1 (a)", "iPhone", None),
        ):
            with self.subTest(version=version, family=family):
                mode = AsyncMock(return_value=True)
                lockdown = SimpleNamespace(
                    all_values={"DeviceName": family, "ProductVersion": version, "DeviceClass": family},
                    paired=True,
                    get_developer_mode_status=mode,
                )
                result = await _describe_device(lockdown, "device")
                if expected_issue:
                    self.assertIn(expected_issue, result.issue)
                    mode.assert_not_awaited()
                else:
                    self.assertIsNone(result.issue)
                    self.assertTrue(result.developer_mode)
                    mode.assert_awaited_once()

    async def test_ios14_and_ios15_are_ready_without_a_developer_mode_toggle(self):
        for version in ("14.0", "14.8.1", "15.6", "15.8.5"):
            with self.subTest(version=version):
                mode = AsyncMock(side_effect=AssertionError("Old iOS has no Developer Mode"))
                lockdown = SimpleNamespace(
                    all_values={"DeviceName": "iPhone", "ProductVersion": version},
                    paired=True, get_developer_mode_status=mode,
                )
                device = await _describe_device(lockdown, "selected")
                self.assertTrue(device.ready)
                self.assertTrue(device.uses_legacy_location)
                self.assertIsNone(device.developer_mode)
                mode.assert_not_awaited()

    async def test_ios16_still_requires_developer_mode(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                mode = AsyncMock(return_value=enabled)
                lockdown = SimpleNamespace(
                    all_values={"DeviceName": "iPhone", "ProductVersion": "16.7.1"},
                    paired=True, get_developer_mode_status=mode,
                )
                device = await _describe_device(lockdown, "selected")
                self.assertEqual(device.ready, enabled)
                self.assertTrue(device.uses_legacy_location)
                mode.assert_awaited_once()

    def test_ready_never_accepts_unsupported_untrusted_or_locked_devices(self):
        for device in (
            Device("device", "iPhone", "13.7", True),
            Device("device", "iPhone", "17.0", True),
            Device("device", "iPhone", "17.3.1", True),
            Device("device", "iPhone", "unknown", True),
            Device("device", "iPhone", "15.6", needs_trust=True),
            Device("device", "iPhone", "15.6", issue="设备已锁定"),
            Device("device", "iPhone", "16.7", False),
        ):
            with self.subTest(device=device):
                self.assertFalse(device.ready)

    async def test_developer_mode_timeout_preserves_device_identity(self):
        lockdown = SimpleNamespace(
            all_values={"DeviceName": "My iPhone", "ProductVersion": "27.0"},
            paired=True,
            get_developer_mode_status=AsyncMock(side_effect=TimeoutError()),
        )
        result = await _describe_device(lockdown, "device")
        self.assertEqual((result.name, result.version), ("My iPhone", "27.0"))
        self.assertIn("超时", result.issue)

    async def test_missing_developer_mode_value_allows_revealing_toggle(self):
        lockdown = SimpleNamespace(
            all_values={"DeviceName": "iPhone", "ProductVersion": "27.0"},
            paired=True,
            get_developer_mode_status=AsyncMock(side_effect=MissingValueError("MissingValue", "device", "27.0")),
        )
        self.assertIs((await _describe_device(lockdown, "device")).developer_mode, False)

    async def test_cancelled_dvt_handshake_finishes_connect_before_closing(self):
        connecting = asyncio.Event()
        release = asyncio.Event()
        closed = []

        async def connect():
            connecting.set()
            await release.wait()
            closed.append("connected")

        async def close():
            closed.append("closed")

        async def use_location():
            async with dvt_location(object()):
                self.fail("Cancellation must not open a location channel")

        with (
            patch("iosrealrun.run.DvtProvider", return_value=SimpleNamespace(connect=connect, close=close)),
            patch("iosrealrun.run.LocationSimulation") as location,
        ):
            worker = asyncio.create_task(use_location())
            await connecting.wait()
            worker.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertEqual(closed, ["connected", "closed"])
        location.assert_not_called()

    async def test_complete_replay_reports_every_lap_and_clears_location(self):
        location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        progress = []
        restored = await self._replay(location, lambda *state: progress.append(state), laps=2)

        self.assertTrue(restored)
        self.assertEqual([lap for lap, _, _ in progress], [1, 1, 1, 2, 2, 2])
        for first, middle, last in (progress[:3], progress[3:]):
            self.assertEqual(first[1], 0)
            self.assertTrue(0 < middle[1] < 1)
            self.assertNotEqual(first[2], middle[2])
            self.assertEqual(last[1], 1)
        self.assertEqual(progress[0][2], progress[-1][2])
        self.assertEqual(location.set.await_count, 6)
        location.clear.assert_awaited_once()

    async def test_open_replay_samples_the_interior_and_finishes_at_last_point(self):
        location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        progress = []
        restored = await self._replay(location, lambda *state: progress.append(state), closed=False)

        self.assertTrue(restored)
        self.assertEqual(len(progress), 3)
        self.assertEqual(progress[0], (1, 0, self._points[0]))
        self.assertTrue(self._points[0]["lat"] < progress[1][2]["lat"] < self._points[-1]["lat"])
        self.assertEqual(progress[-1], (1, 1, self._points[-1]))
        location.clear.assert_awaited_once()

    async def test_stop_while_opening_cancels_setup_and_closes_partial_resources(self):
        stopped = asyncio.Event()
        cancelled = asyncio.Event()
        close_tunnel = AsyncMock()

        async def open_service(stack, udid):
            stack.push_async_callback(close_tunnel)
            stopped.set()
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()

        with patch("iosrealrun.desktop_device._open_location_service", open_service):
            restored = await asyncio.wait_for(replay_route(
                "device", self._points, speed=100, laps=1, interval=1,
                coordinate_system="wgs84", stop_requested=stopped.is_set, pause_requested=lambda: False,
                on_progress=lambda *_: self.fail("Replay emitted a position during setup"),
            ), 1)

        self.assertFalse(restored)
        self.assertTrue(cancelled.is_set())
        close_tunnel.assert_awaited_once()

    async def test_stop_while_paused_clears_without_emitting_another_point(self):
        location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        stopped = paused = False

        def progress(*_):
            nonlocal paused
            paused = True
            asyncio.get_running_loop().call_later(0.01, stop)

        def stop():
            nonlocal stopped
            stopped = True

        restored = await self._replay(location, progress, pause_requested=lambda: paused, stop_requested=lambda: stopped)
        self.assertTrue(restored)
        location.set.assert_awaited_once()
        location.clear.assert_awaited_once()

    async def test_stop_during_pending_location_update_cancels_write_then_clears(self):
        stopped = asyncio.Event()
        actions = []

        async def write(*_):
            stopped.set()
            try:
                await asyncio.sleep(30)
            finally:
                actions.append("write ended")

        async def clear():
            actions.append("clear sent")

        restored = await asyncio.wait_for(self._replay(
            SimpleNamespace(set=write, clear=clear), lambda *_: self.fail("Should not report unsent location"),
            stop_requested=stopped.is_set,
        ), 1)

        self.assertTrue(restored)
        self.assertEqual(actions, ["write ended", "clear sent"])

    async def test_reset_failure_is_reported(self):
        location = SimpleNamespace(clear=AsyncMock(side_effect=ConnectionResetError()))
        with patch("iosrealrun.desktop_device._location_service", self._service(location)):
            with self.assertRaisesRegex(DeviceError, "未能恢复设备定位"):
                await reset_location("device")

    @staticmethod
    def _service(location):
        @asynccontextmanager
        async def service(_udid, **_options):
            yield location

        return service

    _points = [{"lat": 30, "lng": 120}, {"lat": 30.000001, "lng": 120}]

    async def _replay(self, location, on_progress, **overrides):
        options = {
            "speed": 100,
            "laps": 1,
            "interval": 1,
            "coordinate_system": "wgs84",
            "stop_requested": lambda: False,
            "pause_requested": lambda: False,
            "on_progress": on_progress,
        }
        options.update(overrides)
        with patch("iosrealrun.desktop_device._location_service", self._service(location)):
            return await replay_route("device", self._points, **options)
