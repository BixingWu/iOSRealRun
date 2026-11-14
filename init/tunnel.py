"""Own the elevated command-line tunnel for the duration of a replay."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy


@asynccontextmanager
async def tunnel(serial=None):
    async with AsyncExitStack() as stack:
        lockdown = await asyncio.wait_for(
            create_using_usbmux(serial=serial, connection_type="USB", autopair=False), 10
        )
        await stack.enter_async_context(lockdown)
        proxy = await asyncio.wait_for(CoreDeviceTunnelProxy.create(lockdown), 10)
        stack.push_async_callback(proxy.close)
        result = await asyncio.wait_for(stack.enter_async_context(proxy.start_tcp_tunnel()), 20)
        yield result.address, result.port
