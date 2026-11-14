import re

from pymobiledevice3.lockdown import create_using_usbmux, LockdownClient

from pymobiledevice3.services.amfi import AmfiService

from pymobiledevice3.exceptions import NoDeviceConnectedError


_VERSION_PARTS = re.compile(r"([0-9]{1,4})(?:\.([0-9]{1,4})(?:\.[0-9]{1,4})*)?(?:\s+\([^()]+\))?")


def device_version(version):
    if not isinstance(version, str):
        return None
    match = _VERSION_PARTS.fullmatch(version.strip())
    if match is None:
        return None
    return int(match[1]), int(match[2] or 0)


async def get_usbmux_lockdownclient():
    while True:
        try:
            lockdown = await create_using_usbmux(connection_type="USB")
        except NoDeviceConnectedError:
            print("请连接设备后按回车...")
            input()
            continue
        if lockdown.all_values.get("PasswordProtected"):
            await lockdown.close()
            print("请解锁设备后按回车...")
            input()
        else:
            return lockdown

def get_version(lockdown: LockdownClient):
    return lockdown.product_version

async def get_developer_mode_status(lockdown: LockdownClient):
    return await lockdown.get_developer_mode_status()

async def reveal_developer_mode(lockdown: LockdownClient):
    await AmfiService(lockdown).reveal_developer_mode_option_in_ui()

async def enable_developer_mode(lockdown: LockdownClient):
    await AmfiService(lockdown).enable_developer_mode()
