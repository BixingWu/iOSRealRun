import sys
import ctypes
import os
import logging

from driver import connect

logger = logging.getLogger(__name__)

async def init(*, include_serial=False):
    # check if root on mac or Administrator on windows
    if sys.platform == "win32":
        if not ctypes.windll.shell32.IsUserAnAdmin():
            logger.error("请以管理员权限运行。")
            sys.exit(1)
    elif sys.platform == "darwin":
        if os.geteuid() != 0:
            logger.error("请以 root 权限运行。")
            sys.exit(1)
    else:
        logger.error("命令行仅支持 macOS 和 Windows。")
        sys.exit(1)

    # get lockdown client
    lockdown = await connect.get_usbmux_lockdownclient()

    try:
        # check version
        version = connect.get_version(lockdown)
        logger.info("设备系统版本 %s。", version)
        version_number = connect.device_version(version)
        if version_number is None:
            raise RuntimeError("无法读取设备系统版本。请解锁并重新连接设备。")
        if version_number < (14, 0):
            logger.error("仅支持 iOS 或 iPadOS 14 及以上版本。")
            sys.exit(1)

        # Developer Mode is required on iOS/iPadOS 16 and newer.
        if version_number >= (16, 0):
            developer_mode_status = await connect.get_developer_mode_status(lockdown)
            if not developer_mode_status:
                await connect.reveal_developer_mode(lockdown)
                logger.error("请在设备的「设置 → 隐私与安全性 → 开发者模式」中开启，按提示重启并确认后再次运行。")
                sys.exit(1)

        if include_serial:
            if not lockdown.udid:
                raise RuntimeError("无法确认 USB 设备的标识。请重新连接并解锁。")
            return version, lockdown.udid
        return version
    finally:
        await lockdown.close()
