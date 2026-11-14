import asyncio
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
import run
from init import tunnel


ROUTE = Path(__file__).resolve().parents[1] / "ZJGEast.txt"


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_rejects_invalid_settings_before_contacting_usb(self):
        for speed, interval in ((0, 1), (float("nan"), 1), (4.4, float("inf"))):
            with self.subTest(speed=speed, interval=interval):
                settings = SimpleNamespace(routeConfig=ROUTE, v=speed, updateInterval=interval)
                with (
                    patch("main.config.Config", return_value=settings),
                    patch("main.init.init", AsyncMock()) as initialize,
                ):
                    with self.assertRaisesRegex(ValueError, "速度"):
                        await main.main()
                initialize.assert_not_awaited()

    async def test_console_targets_same_device_and_enables_restore(self):
        settings = SimpleNamespace(routeConfig=ROUTE, v=4.4, updateInterval=1)
        replay = AsyncMock()
        mount = AsyncMock()
        with (
            patch("main.config.Config", return_value=settings),
            patch("main.init.init", AsyncMock(return_value=("16.7.1", "legacy-device"))),
            patch("main.mount_legacy_image", mount),
            patch("main.run.run_legacy", replay),
        ):
            await main.main()
        mount.assert_awaited_once_with("legacy-device")
        self.assertEqual(replay.await_args.kwargs["serial"], "legacy-device")
        self.assertTrue(replay.await_args.kwargs["clear_on_finish"])

    async def test_legacy_clear_failure_still_exits_lockdown_context(self):
        lockdown = MagicMock()
        location = SimpleNamespace(clear=AsyncMock(side_effect=OSError("device disconnected")))
        with (
            patch("run.create_using_usbmux", AsyncMock(return_value=lockdown)),
            patch("run.DtSimulateLocation", return_value=location),
            patch("run._run_with_location_simulation", AsyncMock()),
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
            patch("init.tunnel.create_using_usbmux", create_lockdown),
            patch("init.tunnel.CoreDeviceTunnelProxy.create", AsyncMock(return_value=proxy)),
        ):
            with self.assertRaises(asyncio.CancelledError):
                async with tunnel.tunnel("expected-device") as address:
                    self.assertEqual(address, ("::1", 1234))
                    raise asyncio.CancelledError
        create_lockdown.assert_awaited_once_with(serial="expected-device", connection_type="USB", autopair=False)
        self.assertEqual(closed, ["tunnel", "proxy", "lockdown"])
