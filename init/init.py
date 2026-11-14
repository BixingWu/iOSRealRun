import sys
import ctypes
import os

from driver import connect

async def init(*, include_serial=False):
    # check if root on mac or Administrator on windows
    if sys.platform == "win32":
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("请以管理员权限运行")
            sys.exit(1)
    elif sys.platform == "darwin":
        if os.geteuid() != 0:
            print("请以root权限运行")
            sys.exit(1)
    else:
        print("仅支持macOS和Windows")
        sys.exit(1)

    # get lockdown client
    lockdown = await connect.get_usbmux_lockdownclient()

    try:
        # check version
        version = connect.get_version(lockdown)
        print(f"Your system version is {version}")
        version_number = connect.device_version(version)
        if version_number is None:
            raise RuntimeError("无法读取设备系统版本。请解锁并重新连接设备。")
        if version_number < (14, 0):
            print(f"仅支持14及以上版本")
            sys.exit(1)

        # Developer Mode is required on iOS/iPadOS 16 and newer.
        if version_number >= (16, 0):
            developer_mode_status = await connect.get_developer_mode_status(lockdown)
            if not developer_mode_status:
                await connect.reveal_developer_mode(lockdown)
                print("您未开启开发者模式，请打开设备的 设置-隐私与安全性-开发者模式 来开启，开启后需要重启并输入密码，完成后再次运行此程序")
                sys.exit(1)

        if include_serial:
            if not lockdown.udid:
                raise RuntimeError("无法确认 USB 设备的标识。请重新连接并解锁。")
            return version, lockdown.udid
        return version
    finally:
        await lockdown.close()
