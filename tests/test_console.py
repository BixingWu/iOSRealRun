import asyncio
import io
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pymobiledevice3.exceptions import NoDeviceConnectedError

from iosrealrun import main, run
from iosrealrun.driver import connect
from iosrealrun.init import tunnel
from iosrealrun.paths import bundled_route


ROUTE = bundled_route("ZJGEast.txt")


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_rejects_invalid_settings_before_contacting_usb(self):
        for speed, interval in ((0, 1), (float("nan"), 1), (4.4, float("inf"))):
            with self.subTest(speed=speed, interval=interval):
                settings = SimpleNamespace(routeConfig=ROUTE, v=speed, updateInterval=interval)
                with (
                    patch("iosrealrun.main.config.Config", return_value=settings),
                    patch("iosrealrun.main.init.init", AsyncMock()) as initialize,
                ):
                    with self.assertRaisesRegex(ValueError, "速度"):
                        await main.main()
                initialize.assert_not_awaited()

    async def test_console_targets_same_device_and_enables_restore_with_cp1252_stdout(self):
        settings = SimpleNamespace(routeConfig=ROUTE, v=4.4, updateInterval=1)
        replay = AsyncMock()
        mount = AsyncMock()
        with (
            io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as output,
            redirect_stdout(output),
            self.assertLogs("iosrealrun.main", level="INFO") as logs,
            patch("iosrealrun.main.config.Config", return_value=settings),
            patch("iosrealrun.main.init.init", AsyncMock(return_value=("16.7.1", "legacy-device"))),
            patch("iosrealrun.main.mount_legacy_image", mount),
            patch("iosrealrun.main.run.run_legacy", replay),
        ):
            await main.main()
            self.assertEqual(output.tell(), 0)
        self.assertTrue(any("按 Ctrl+C 停止并尝试恢复定位" in line for line in logs.output))
        mount.assert_awaited_once_with("legacy-device")
        self.assertEqual(replay.await_args.kwargs["serial"], "legacy-device")
        self.assertEqual(replay.await_args.kwargs["loop_count"], 100)
        self.assertTrue(replay.await_args.kwargs["clear_on_finish"])

    async def test_usb_prompts_use_logging_and_wait_for_input(self):
        locked = SimpleNamespace(all_values={"PasswordProtected": True}, close=AsyncMock())
        unlocked = SimpleNamespace(all_values={})
        find_device = AsyncMock(side_effect=[NoDeviceConnectedError(), locked, unlocked])
        with (
            io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as output,
            redirect_stdout(output),
            self.assertLogs("iosrealrun.driver.connect", level="INFO") as logs,
            patch("iosrealrun.driver.connect.create_using_usbmux", find_device),
            patch("builtins.input", return_value="") as prompt,
        ):
            self.assertIs(await connect.get_usbmux_lockdownclient(), unlocked)
            self.assertEqual(output.tell(), 0)
        self.assertEqual(prompt.call_count, 2)
        self.assertIn("请连接设备后按回车", logs.output[0])
        self.assertIn("请解锁设备后按回车", logs.output[1])
        locked.close.assert_awaited_once()

    async def test_lap_completion_uses_logging(self):
        with (
            io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as output,
            redirect_stdout(output),
            self.assertLogs("iosrealrun.run", level="INFO") as logs,
            patch("iosrealrun.run.run1", AsyncMock(return_value=True)),
        ):
            await run._run_with_location_simulation(object(), [], 4.4, loop_count=1)
            self.assertEqual(output.tell(), 0)
        self.assertIn("已完成第 1 圈", logs.output[0])

    async def test_legacy_clear_failure_still_exits_lockdown_context(self):
        lockdown = MagicMock()
        location = SimpleNamespace(clear=AsyncMock(side_effect=OSError("device disconnected")))
        with (
            patch("iosrealrun.run.create_using_usbmux", AsyncMock(return_value=lockdown)),
            patch("iosrealrun.run.DtSimulateLocation", return_value=location),
            patch("iosrealrun.run._run_with_location_simulation", AsyncMock()),
        ):
            with self.assertRaisesRegex(RuntimeError, "未能恢复设备定位"):
                await run.run_legacy([], 4.4, clear_on_finish=True, serial="legacy-device")
        lockdown.__aexit__.assert_awaited_once()

    async def test_kernel_tunnel_disposes_proxy_and_lockdown_after_cancellation(self):
        closed = []

        @asynccontextmanager
        async def lockdown_context():
            try:
                yield
            finally:
                closed.append("lockdown")

        @asynccontextmanager
        async def proxy_context():
            try:
                yield SimpleNamespace(address="::1", port=1234)
            finally:
                closed.append("tunnel")

        async def close_proxy():
            closed.append("proxy")

        proxy = SimpleNamespace(start_tcp_tunnel=proxy_context, close=close_proxy)
        create_lockdown = AsyncMock(return_value=lockdown_context())
        with (
            patch("iosrealrun.init.tunnel.create_using_usbmux", create_lockdown),
            patch("iosrealrun.init.tunnel.CoreDeviceTunnelProxy.create", AsyncMock(return_value=proxy)),
        ):
            with self.assertRaises(asyncio.CancelledError):
                async with tunnel.tunnel("expected-device") as address:
                    self.assertEqual(address, ("::1", 1234))
                    raise asyncio.CancelledError
        create_lockdown.assert_awaited_once_with(serial="expected-device", connection_type="USB", autopair=False)
        self.assertEqual(closed, ["tunnel", "proxy", "lockdown"])
