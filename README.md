# iOSRealRun

通过 USB 在 iPhone 或 iPad 上按指定路线模拟定位，兼容 **iOS 26、27**，并提供 **iOS 14–16** 的桌面连接方式。支持地图绘制、TXT / JSON / GPX 导入、速度与圈数设置，以及暂停、继续和恢复定位。

![紫金港东操场的路线和橙色模拟位置标记](docs/images/desktop.png)

绘制与回放默认使用「城市街图」，可切换清爽、街道、夜色、经典街图或纯轨迹。手绘支持平滑补点，也可以在地图上放置连笔 IKUN、爱心、无限符号或椭圆。上图使用内置路线和演示位置。

「本地预演」可以拖动进度条，也可以用 2× 或 4× 在电脑上走一遍路线。「场地对照」可以在主窗口和绘制窗口并排查看自己的地图截图。连笔 IKUN 默认沿所选操场的长边排布。放好图形后可以直接拖动、缩放或旋转，也可以按场地保存多条可继续编辑的草稿。

## 下载

**[下载桌面版 v0.2.0-beta.5](https://github.com/BixingWu/iOSRealRun/releases/tag/v0.2.0-beta.5)**

| 平台 | 下载 | 启动方式 |
| --- | --- | --- |
| Windows x64 | [ZIP](https://github.com/BixingWu/iOSRealRun/releases/download/v0.2.0-beta.5/iOSRealRun-Windows-x64.zip) | 完整解压，打开 `iOSRealRun/iOSRealRun.exe`。 |
| macOS 15+ · Apple Silicon | [ZIP](https://github.com/BixingWu/iOSRealRun/releases/download/v0.2.0-beta.5/iOSRealRun-macOS-arm64.zip) | 解压后打开 `iOSRealRun.app`。 |
| Ubuntu 22.04 / 24.04 · x64 | [tar.gz](https://github.com/BixingWu/iOSRealRun/releases/download/v0.2.0-beta.5/iOSRealRun-Linux-x64.tar.gz) | 解压后运行 `iOSRealRun/iOSRealRun`。 |

压缩包自带运行环境和五条示例路线，无需安装 Python。请保留解压后的完整目录。

iOS 14–16 通过 USB 连接时，请准备匹配的 Apple 开发者镜像，放置方法见[旧版系统说明](docs/usage.md#ios-14-16-桌面连接)。下载后可按 [SHA-256 校验清单](https://github.com/BixingWu/iOSRealRun/releases/download/v0.2.0-beta.5/SHA256SUMS.txt)核对文件。

macOS 和 Linux 为实验构建，尚未完成 USB 真机回放验证。macOS 应用未签名和公证；Linux 需要桌面环境及 `usbmuxd` 等系统依赖。见 [macOS 使用说明](docs/usage.md#macos)和 [Linux 安装命令](docs/usage.md#linux)。

**Code → Download ZIP** 下载的是源码，使用方式见[从源码启动](#从源码启动)。

## 使用方法

1. **连接设备。** Windows 先安装 [Apple Devices 或 iTunes](https://support.apple.com/118290)，确认能识别设备。用数据线连接 iPhone / iPad，并解锁屏幕。
2. **确认信任。** 在程序中点击「连接并信任」，再在设备上确认「信任这台电脑」。
3. **准备设备。** iOS 14 / 15 不需要开发者模式，开始时会自动挂载本地开发者镜像，见 [旧版系统说明](docs/usage.md#ios-14-16-桌面连接)。iOS 16 及以上请前往设备的 **设置 → 隐私与安全性 → 开发者模式**，按提示重启并确认。找不到开关时，先点击程序中的「显示开发者模式开关」。
4. **选择路线。** 使用预置路线，点击「绘制路线」在地图上选点，或通过「导入文件」「粘贴坐标」载入自己的路线。
5. **开始模拟。** 设置速度和圈数，确认设备已识别后点击「开始模拟」。连接多台设备时，先在设备栏选择目标。

默认速度为 **5 米/秒**，也可以直接输入配速 **3:20/km**。预置路线和闭合图形默认跑 **100 圈**，修改圈数时可在旁边看到总里程，填 `0` 表示持续循环。手绘、连笔 IKUN 和自己导入的路线默认从起点走到终点一次。点击「使用帮助」可查看当前版本和便携版的构建编号。

暂停时保留当前模拟位置，停止时恢复定位。若中途断开设备，请重新连接并点击「恢复定位」，完成后再拔线。

桌面版通常不需要管理员权限。详细操作见[使用手册](docs/usage.md)。

## 兼容性

| 设备系统 | 使用方式 |
| --- | --- |
| iOS 26、27 / iPadOS 26.4 | 桌面版，USB 连接并开启开发者模式。 |
| iOS / iPadOS 17.4–18.x | 已接入桌面连接流程，尚未完成逐版本真机验证。 |
| iOS / iPadOS 17.0–17.3 | 当前不支持。 |
| iOS / iPadOS 14–16 | 桌面版通过 USB 直接连接，自动挂载本地匹配的开发者镜像；16 仍需开发者模式。Windows + iOS 15.6 已获用户实测可用反馈，其他版本尚待真机验证。 |

电脑环境及旧系统的具体要求见[兼容性说明](docs/usage.md#兼容性)。

## 示例路线

五条路线随程序提供，也可以单独下载。坐标系均为 **BD-09**。

| 路线 | 文件 |
| --- | --- |
| 紫金港东操场 | [ZJGEast.txt](https://github.com/BixingWu/iOSRealRun/blob/main/routes/ZJGEast.txt) |
| 紫金港西操场 | [ZJGWest.txt](https://github.com/BixingWu/iOSRealRun/blob/main/routes/ZJGWest.txt) |
| 玉泉操场 | [YuQuan.txt](https://github.com/BixingWu/iOSRealRun/blob/main/routes/YuQuan.txt) |
| 西溪操场 | [XiXi.txt](https://github.com/BixingWu/iOSRealRun/blob/main/routes/XiXi.txt) |
| 海宁操场 | [HaiNing.txt](https://github.com/BixingWu/iOSRealRun/blob/main/routes/HaiNing.txt) |

导入自己的 TXT / JSON 时，在「坐标设置」中选择对应坐标系：百度为 BD-09，高德 / 腾讯为 GCJ-02，GPS 为 WGS 84。地图绘制和 GPX 自动使用 WGS 84。见[路线格式与绘制说明](docs/usage.md#路线与坐标)。

## 从源码启动

以下命令适用于当前 `main` 分支，需要 64 位 [Python 3.12](https://www.python.org/downloads/)。

### Windows

下载或克隆仓库后，双击根目录的 `Start-iOSRealRun.bat`。首次运行会创建独立环境并安装依赖，需要联网。

```powershell
# 只配置环境
.\Start-iOSRealRun.bat -SetupOnly

# 指定 Python 路径
.\Start-iOSRealRun.bat -Python "C:\path\to\python.exe"
```

### macOS / Linux

Linux 请先安装[系统依赖](docs/usage.md#linux)，然后在项目目录运行：

```sh
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m iosrealrun
```

配置文件和命令行用法见[使用手册](docs/usage.md#配置文件)，测试与打包见[参与开发](CONTRIBUTING.md)。

## 遇到问题

设备未连接时，先检查数据线、设备信任和开发者模式；位置整体偏移时，先检查坐标系。更多情况见[常见问题](docs/usage.md#常见问题)。

仍有问题可[提交 Issue](https://github.com/BixingWu/iOSRealRun/issues/new/choose)，附上电脑系统、设备型号、完整系统版本、软件版本、复现步骤和错误提示。截图请遮住设备标识和个人路线。

## 来源与许可

基于 [iOSRealRun-cli-18](https://github.com/MTDickens/iOSRealRun-cli-18) 修改，桌面操作流程参考 [iOSFakeRun](https://github.com/Mythologyli/iOSFakeRun)。设备通信由 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 提供，地图来自 [OpenStreetMap](https://www.openstreetmap.org/copyright)。

项目使用 [MPL-2.0](LICENSE)，依赖许可见[第三方组件说明](docs/third-party-notices.md)。
