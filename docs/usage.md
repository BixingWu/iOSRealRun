# 使用手册

[下载与快速开始](../README.md#使用方法) · [路线与坐标](#路线与坐标) · [配置文件](#配置文件) · [命令行](#命令行) · [常见问题](#常见问题)

## 电脑环境

### Windows

安装 [Apple Devices 或 iTunes](https://support.apple.com/118290)，确认它能识别连接的 iPhone / iPad，再打开 iOSRealRun。便携包请完整解压，保留 EXE 旁的 `_internal` 文件夹。

源码版使用 Python 3.12，双击根目录的 `Start-iOSRealRun.bat`。启动器创建 `.pvenv` 并安装依赖，不需要 Conda。可用 `-SetupOnly` 只配置环境，或用 `-Python "C:\path\to\python.exe"` 指定解释器。

### macOS

便携包适用于 macOS 15+、Apple Silicon。解压得到 `iOSRealRun.app`，可拖入「应用程序」。当前没有 Intel Mac 安装包。

应用尚未经过 Developer ID 签名和公证。若被系统拦截，请参考 [Apple 的应用打开说明](https://support.apple.com/guide/mac-help/mh40616/mac)，也可以按 [README](../README.md#从源码启动)使用源码版。

USB 通信使用 macOS 自带的设备服务。当前 macOS 包为实验构建，尚未完成 USB 真机回放验证。

### Linux

便携包适用于 Ubuntu 22.04 / 24.04 x64，需要桌面环境。初次使用先安装设备服务和界面依赖：

```sh
sudo apt update
sudo apt install usbmuxd libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libgl1 fonts-noto-cjk
tar -xzf iOSRealRun-Linux-x64.tar.gz
./iOSRealRun/iOSRealRun
```

USB 设备通信需要 `usbmuxd` 服务可用。源码版也需要这些系统依赖。其他发行版请安装对应软件包，参考 [pymobiledevice3 安装说明](https://github.com/doronz88/pymobiledevice3/blob/v11.54.0/docs/installation.md)。当前 Linux 包为实验构建，尚未完成 USB 真机回放验证。

### 下载校验

Release 中的 `SHA256SUMS.txt` 列出了各压缩包的 SHA-256。计算下载文件的校验值并与清单对照：

| 系统 | 命令 |
| --- | --- |
| Windows PowerShell | `Get-FileHash 文件名 -Algorithm SHA256` |
| macOS | `shasum -a 256 文件名` |
| Linux | `sha256sum 文件名` |

## 路线与坐标

### 绘制和回放

点击「绘制路线」，在地图上依次点击添加坐标。拖动平移，滚轮或 `+ / −` 缩放；也可以输入纬度、经度定位。至少两个点后点击「使用路线」。相邻点直接连线，不会自动沿道路规划。

地图依赖 OpenStreetMap 在线底图，已经加载的区域会缓存在本机。底图不可用时，仍可使用预置路线或导入文件。

预置路线默认闭合。导入、粘贴和绘制的路线默认只从起点走到终点；勾选「闭合路线」后，会补上终点到起点的一段，预览中以虚线表示。闭合路线可设置圈数，`0` 表示持续循环。

速度范围为 `0.1–30 m/s`。暂停时设备停在当前模拟位置，停止或正常结束时会尝试恢复定位。连接过程中取消操作，可能需要等待约 15 秒清理服务。

### 导入格式

支持 TXT、JSON 和 GPX，也可以点击「粘贴坐标」。JSON / TXT 推荐使用以下格式，`lat` 为纬度，`lng` 为经度：

```json
[
  {"lat": 30.1000, "lng": 120.1000},
  {"lat": 30.1008, "lng": 120.1006},
  {"lat": 30.1012, "lng": 120.1010}
]
```

兼容项目原有的逗号分隔 TXT 坐标。导入 TXT / JSON 后，请在「坐标设置」中选择文件使用的坐标系：

| 坐标来源 | 坐标系 |
| --- | --- |
| 百度地图、五条内置路线 | BD-09 |
| 高德 / 腾讯地图 | GCJ-02 |
| GPS、地图绘制、GPX | WGS 84 |

GPX 支持单条连续轨迹或路线，不自动拼接多条轨迹或多个轨迹段。只读取经纬度，时间和海拔不参与回放。导入文件最多 2 MiB、20,000 个点。

### 本地记录

最近使用的路线、坐标系和闭合选项会在下次启动时恢复。Windows 记录在 `%LOCALAPPDATA%\iOSRealRun\last-route.json`，macOS 在 `~/Library/Application Support/iOSRealRun/last-route.json`。删除该文件可回到默认路线。

Windows 地图缓存在 `%LOCALAPPDATA%\iOSRealRun\map-tiles.sqlite3`，macOS 在 `~/Library/Caches/iOSRealRun/`。

## 配置文件

当前源码的默认值在 [config.example.yaml](../config.example.yaml)。可以创建 `config.yaml` 覆盖默认值，或使用优先级更高的 `config.local.yaml` 保存个人设置。两个覆盖文件均由 Git 忽略。

```yaml
v: 4.4
routeConfig: "routes/XiXi.txt"
coordinateSystem: "bd09"
updateInterval: 1.0
```

`v` 是速度，单位米/秒；`updateInterval` 是更新间隔，单位秒，范围 `0.1–10`。桌面版已有路线记录时，会优先恢复最近使用的路线。

| 运行方式 | 配置文件位置 |
| --- | --- |
| 当前源码 | 项目根目录 |
| Windows / Linux 便携包 | 可执行文件所在目录 |
| macOS `.app` | `~/Library/Application Support/iOSRealRun/` |

相对路线路径以配置文件所在目录为准。内置路线也可直接填写文件名，例如 `XiXi.txt`，无需另行复制路线。

## 命令行

命令行支持 Windows / macOS，按配置持续循环。以下命令适用于当前 `main` 源码。

Windows：

```powershell
.\Start-iOSRealRun.bat -Console
```

macOS：

```sh
sudo "$PWD/.venv/bin/python" -m iosrealrun.main
```

命令行隧道需要管理员 / root 权限。iOS 14–16 会尝试挂载开发者磁盘镜像，首次可能需要联网。已手动挂载时，Windows 启动器可加 `-SkipMount`，模块命令可加 `--skip-mount`。按 `Ctrl+C` 结束，并等待定位清理完成。

若提示路线采样点超过 125,000 个，请缩短路线、增大更新间隔，或改用桌面版。

## 兼容性

**兼容 iOS 26、27 和 iPadOS 26.4。** 桌面版需使用 USB 数据线连接设备，确认信任并开启开发者模式，无需手动挂载开发者磁盘镜像。

| 其他设备系统 | 支持情况 |
| --- | --- |
| iOS / iPadOS 17.4–18.x | 已接入桌面连接流程，尚未完成逐版本真机验证。 |
| iOS / iPadOS 17.0–17.3 | 不支持当前连接方式。 |
| iOS / iPadOS 14–16 | 保留命令行入口，需要匹配的开发者磁盘镜像；16 还需开发者模式。尚未完成旧设备回归。 |
| 低于 iOS / iPadOS 14 | 不支持。 |

Windows 11 x64 为当前开发和验证环境，Windows 10 x64 使用同一便携包。macOS 15+ / Apple Silicon、Ubuntu 22.04 / 24.04 x64 提供实验构建，已检查构建和界面启动，尚未完成 USB 真机回放验证。Windows ARM、Intel Mac 和其他 Linux 发行版暂无专门安装包。

## 常见问题

**一直显示未连接设备**

Windows 先确认 Apple Devices / iTunes 能识别设备。检查数据线是否支持传输，解锁设备并确认信任，再点击「刷新」。开启开发者模式重启后，也需要重新解锁。

**找不到开发者模式开关**

先连接设备，在程序中点击「显示开发者模式开关」，然后前往设备的「设置 → 隐私与安全性」。开启后按提示重启并确认，详见 [Apple 开发者模式说明](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)。

**「开始模拟」不能点击**

检查设备栏提示、开发者模式和路线是否有效，以及速度和圈数下方的提示。未连接设备时仍可选路线、绘图和预览。

**不支持当前版本，或无法建立定位服务**

先对照[兼容性](#兼容性)，再重新连接设备，检查信任与开发者模式。提交 Issue 时附上完整系统版本和错误文本。

**位置出现整体偏移**

检查「坐标设置」是否与文件来源匹配。百度坐标应选择 BD-09，高德 / 腾讯选择 GCJ-02，GPS 选择 WGS 84。

**地图空白或只显示部分底图**

检查网络能否访问 OpenStreetMap，未加载的区域稍后会自动重试。使用预置路线和导入文件不依赖在线地图。

**停止后定位没有恢复**

保持设备连接，重新打开程序并点击「恢复定位」。若设备服务仍无响应，可重启设备。恢复完成前不要拔线。

**源码启动提示 `No Python at ...`**

旧虚拟环境指向的 Python 可能已被删除或移动。启动器会备份失效环境并重建；请先安装 Python 3.12，必要时用 `Start-iOSRealRun.bat -Python "C:\path\to\python.exe"` 指定路径。
