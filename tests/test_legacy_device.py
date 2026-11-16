import asyncio
import tempfile
import unittest
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pymobiledevice3.exceptions import AlreadyMountedError

from iosrealrun.desktop_device import Device, DeviceError, _location_service, replay_route, reset_location
from iosrealrun.legacy_image import find_legacy_image, legacy_image_directory


class LegacyImageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.user = Path(temp.name) / "用户目录"
        self.bundled = Path(temp.name) / "_internal"
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch("iosrealrun.legacy_image.config_directory", return_value=self.user))
        patches.enter_context(patch("iosrealrun.legacy_image.RESOURCE_ROOT", self.bundled))

    def image(self, root, version):
        folder = root / "DeveloperDiskImage" / version
        folder.mkdir(parents=True)
        image = folder / "DeveloperDiskImage.dmg"
        signature = folder / "DeveloperDiskImage.dmg.signature"
        image.write_bytes(b"image")
        signature.write_bytes(b"signature")
        return image, signature

    def test_bundled_ios156_image_is_found_independently_of_working_directory(self):
        image = self.image(self.bundled, "15.6")
        self.assertEqual(find_legacy_image("15.6"), image)
        self.assertEqual(find_legacy_image("15.6.1"), image)
        self.assertEqual(find_legacy_image("15.6 (a)"), image)

    def test_exact_patch_image_takes_priority_over_minor_image(self):
        self.image(self.user, "15.6")
        exact = self.image(self.bundled, "15.6.1")
        self.assertEqual(find_legacy_image("15.6.1"), exact)

    def test_user_supplied_image_overrides_bundle_for_same_version(self):
        self.image(self.bundled, "15.6")
        local = self.image(self.user, "15.6")
        self.assertEqual(find_legacy_image("15.6"), local)

    def test_missing_empty_or_unrelated_images_are_not_mounted(self):
        image, signature = self.image(self.bundled, "15.6")
        self.assertIsNone(find_legacy_image("16.6"))
        self.assertIsNone(find_legacy_image("15.7"))
        signature.unlink()
        self.assertIsNone(find_legacy_image("15.6"))
        signature.write_bytes(b"")
        self.assertIsNone(find_legacy_image("15.6"))
        signature.write_bytes(b"signature")
        image.write_bytes(b"")
        self.assertIsNone(find_legacy_image("15.6"))

    def test_invalid_and_modern_versions_never_resolve_legacy_images(self):
        for version in ("../15.6", "13.7", "17.0", "27.0", "", None):
            with self.subTest(version=version):
                self.assertIsNone(find_legacy_image(version))
                with self.assertRaises(ValueError):
                    legacy_image_directory(version)

    def test_missing_image_help_uses_user_writable_minor_version_directory(self):
        self.assertEqual(legacy_image_directory("15.6.1"), self.user / "DeveloperDiskImage" / "15.6")


class LegacyConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lockdown = MagicMock(
            all_values={"DeviceName": "iPhone", "ProductVersion": "15.6"}, paired=True,
        )
        self.lockdown.__aenter__.return_value = self.lockdown
        self.mounter = SimpleNamespace(
            is_image_mounted=AsyncMock(return_value=False), mount=AsyncMock(), close=AsyncMock(),
        )
        self.location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        self.image = (Path("15.6/DeveloperDiskImage.dmg"), Path("15.6/DeveloperDiskImage.dmg.signature"))
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch("iosrealrun.desktop_device._read_device",
                                    AsyncMock(return_value=Device("selected", "iPhone", "15.6"))))
        self.create = patches.enter_context(patch("iosrealrun.desktop_device.create_using_usbmux",
                                                  AsyncMock(return_value=self.lockdown)))
        self.find = patches.enter_context(patch("iosrealrun.desktop_device.find_legacy_image", return_value=self.image))
        self.mounter_class = patches.enter_context(patch("iosrealrun.desktop_device.DeveloperDiskImageMounter",
                                                         return_value=self.mounter))
        self.simulator = patches.enter_context(patch("iosrealrun.desktop_device.DtSimulateLocation",
                                                     return_value=self.location))
        self.tunnel = patches.enter_context(patch("pymobiledevice3.remote.userspace_tunnel.UserspaceRsdTunnel"))

    async def replay(self, stop_requested=lambda: False):
        return await replay_route(
            "selected", [{"lat": 30, "lng": 120}, {"lat": 30.000001, "lng": 120}],
            speed=100, laps=1, interval=1, coordinate_system="wgs84",
            stop_requested=stop_requested, pause_requested=lambda: False, on_progress=lambda *_: None,
        )

    async def test_replay_mounts_selected_device_and_restores_location(self):
        self.assertTrue(await self.replay())
        self.create.assert_awaited_once_with(serial="selected", connection_type="USB", autopair=False)
        self.mounter_class.assert_called_once_with(self.lockdown)
        self.mounter.mount.assert_awaited_once_with(*self.image)
        self.mounter.close.assert_awaited_once()
        self.simulator.assert_called_once_with(self.lockdown)
        self.assertGreaterEqual(self.location.set.await_count, 3)
        self.location.clear.assert_awaited_once()
        self.lockdown.__aexit__.assert_awaited_once()
        self.tunnel.assert_not_called()

    async def test_reset_reuses_mounted_image_without_requiring_local_files(self):
        self.mounter.is_image_mounted.return_value = True
        await reset_location("selected")
        self.find.assert_not_called()
        self.mounter.mount.assert_not_awaited()
        self.location.clear.assert_awaited_once()
        self.lockdown.__aexit__.assert_awaited_once()
        self.tunnel.assert_not_called()

    async def test_missing_image_has_gui_help_and_closes_connections(self):
        self.find.return_value = None
        with self.assertRaisesRegex(DeviceError, "未找到 iOS 15.6.*开发者镜像"):
            await self.replay()
        self.mounter.mount.assert_not_awaited()
        self.simulator.assert_not_called()
        self.mounter.close.assert_awaited_once()
        self.lockdown.__aexit__.assert_awaited_once()

    async def test_mount_failure_never_sends_a_location_and_closes_connections(self):
        self.mounter.mount.side_effect = ConnectionResetError("USB disconnected")
        with self.assertRaises(DeviceError):
            await self.replay()
        self.location.set.assert_not_awaited()
        self.mounter.close.assert_awaited_once()
        self.lockdown.__aexit__.assert_awaited_once()

    async def test_stop_during_mount_cancels_and_cleans_up(self):
        stopped = asyncio.Event()
        cancelled = asyncio.Event()

        async def mount(*_):
            stopped.set()
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()

        self.mounter.mount.side_effect = mount
        self.assertFalse(await asyncio.wait_for(self.replay(stopped.is_set), 2))
        self.assertTrue(cancelled.is_set())
        self.mounter.close.assert_awaited_once()
        self.lockdown.__aexit__.assert_awaited_once()
        self.simulator.assert_not_called()

    async def test_device_locked_since_discovery_is_not_mounted(self):
        self.lockdown.all_values["PasswordProtected"] = True
        with self.assertRaisesRegex(DeviceError, "设备已锁定"):
            await self.replay()
        self.mounter_class.assert_not_called()
        self.simulator.assert_not_called()
        self.lockdown.__aexit__.assert_awaited_once()

    async def test_image_mounted_by_another_client_during_setup_is_accepted(self):
        self.mounter.mount.side_effect = AlreadyMountedError()
        await reset_location("selected")
        self.location.clear.assert_awaited_once()

    async def test_modern_ios_keeps_the_existing_tunnel_path(self):
        @asynccontextmanager
        async def dvt(rsd):
            self.assertEqual(rsd.udid, "selected")
            yield self.location

        for version in ("17.4", "18.7", "26.4", "27.0"):
            with self.subTest(version=version):
                tunnel = SimpleNamespace(aopen=AsyncMock(return_value=SimpleNamespace(udid="selected")),
                                         aclose=AsyncMock())
                self.tunnel.return_value = tunnel
                with (
                    patch("iosrealrun.desktop_device._read_device",
                          AsyncMock(return_value=Device("selected", "iPhone", version, True))),
                    patch("iosrealrun.desktop_device.dvt_location", dvt),
                ):
                    async with _location_service("selected") as location:
                        self.assertIs(location, self.location)
                tunnel.aclose.assert_awaited_once()
        self.create.assert_not_awaited()
        self.mounter_class.assert_not_called()
        self.simulator.assert_not_called()
