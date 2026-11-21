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

点击「绘制路线」，选择「手绘选点」，在地图上依次点击。拖动可以平移，滚轮或 `+ / −` 可以缩放，也可以输入纬度、经度定位。两个点画出直线，从第三个点起，「平滑补点」会将折角圆滑处理，沿曲线约每 3 米补一个点。首尾保留原位，长路线自动增大间距以适应 20,000 点的上限。取消勾选即可查看原折线，撤销每次移除一个手绘点。

在绘制方式中选择「连笔 IKUN」「G.E.M.（解解）」「爱心」「无限符号 ∞」或「椭圆」，然后在地图上点选放置区域的两个对角。图形会在框内留出边距，第三次点击可调整第二个角。切换图形会复用这块区域，切回手绘时可以继续编辑原草稿。「显示参考路线」用灰蓝色虚线标出打开绘制窗口前的路线，方便在操场内放置图形。确认预览后点击「使用路线」。

选择操场路线后打开「绘制路线」，IKUN 和 G.E.M. 默认「沿操场长边」。在场地上选两个斜对角，虚线框和字样会随参考跑道一起倾斜。再次点击可调整第二个角，隐藏参考线后字样会保留当前方向。参考路线为开放步道或接近圆形时，默认「沿选框长边」。手动选择「横排」或「竖排」可以按地图的水平或垂直方向排列字样。

图形放好后，拖中央十字可整体移动，拖四个角可等比例缩放，拖圆形手柄可旋转。点「撤销」可退回上一次调整。手绘路线可勾选「闭合路线」查看返回起点的路径。

点击「保存草稿」，输入场地和草稿名称。下次在「绘制路线」中点击「打开草稿」，按场地选择即可继续编辑手绘选点或图形。沿用同一名称保存会更新已打开的草稿，修改名称或场地则会另存一份。草稿保存在本机用户目录，移动便携版程序后仍可打开。

主窗口和绘制窗口默认使用「城市街图」，水面、绿地、建筑和道路分别着色，优先标注有数据的学校、场馆和中文地名。也可以切换「清爽」「街道」「夜色」「经典街图」或「纯轨迹」。回放时橙色圆点沿蓝色轨迹移动，点击「全览」可回到整条路线。

点击「本地预演」可在电脑上播放一遍路线，未接手机也可以使用。拖动地图下方的进度条可以跳到路线上的任意位置，右侧可选 1×、2× 或 4×。预演速度围绕设定值平滑波动，最大偏差为 3%，标记最多偏离屏幕上的线 3 像素。「开始模拟」使用路线设置中的速度。

彩色底图来自 [OpenFreeMap](https://openfreemap.org/)，使用 OpenMapTiles 和 OpenStreetMap 数据。在线地图会按当前视野请求图块。在底图菜单切换到纯轨迹视图后，无需联网也能绘制和回放路线。

预置路线、爱心、无限符号和椭圆默认闭合，速度为 5 米/秒（3:20 /km），默认跑 100 圈。速度和配速联动，在配速框输入 `3:20/km` 或 `320` 都表示每公里 3 分 20 秒。圈数旁显示总里程。手绘、连笔字样、导入和粘贴的路线默认从起点走到终点一次。勾选「闭合路线」后，预览用虚线连接终点和起点，并恢复闭合时的圈数。圈数填 `0` 表示持续循环。

点击主窗口右上的「使用帮助」可查看版本号、便携版的构建编号，并打开在线使用手册。

### 地图上的场地范围

有本地场地数据时，主窗口和「绘制路线」会在底图上画出同一条红色参考范围。可以平移、缩放或切换底图，也可以在「场地范围」菜单中隐藏红线、选择其他场地或全览整个范围。只有场地名称时，菜单会显示「待补轮廓」。

如果红线偏了，打开「场地范围」里的「对齐地标」，在下拉框选择一个球场角点或路口，再点击它在底图上的真实位置。至少使用三个分散且不共线的地标，尽量覆盖范围的各个方向。红线利用这些点估算平移、旋转和比例。窗口显示的拟合差是地标之间的吻合程度。保存后，两个窗口都会采用这份本机校准。

将场地数据放入配置目录下的 `场地参考/boundaries.json`。Windows 和 Linux 便携版的配置目录在可执行文件旁，macOS 便携版在 `~/Library/Application Support/iOSRealRun`。也可以用「打开场地数据目录」临时载入。每个场地的 `outline` 依次记录原图红线的顶点，`pixel` 使用同一张原图的像素坐标，原点在左上。`wgs84` 按经度、纬度排列。以下为格式示意。

```json
[
  {
    "title": "示例球场",
    "routes": ["示例路线"],
    "outline": [[10, 10], [190, 10], [190, 140], [10, 140]],
    "landmarks": [
      {"name": "西北角", "pixel": [30, 25], "wgs84": [10.0000, 45.0010]},
      {"name": "东北角", "pixel": [170, 25], "wgs84": [10.0020, 45.0010]},
      {"name": "西南角", "pixel": [30, 125], "wgs84": [10.0000, 45.0000]}
    ]
  }
]
```

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

OpenStreetMap 标准底图在 Windows 上缓存在 `%LOCALAPPDATA%\iOSRealRun\map-tiles.sqlite3`，macOS 上缓存在 `~/Library/Caches/iOSRealRun/`。

## 配置文件

当前源码的默认值在 [config.example.yaml](../config.example.yaml)。可以创建 `config.yaml` 覆盖默认值，或使用优先级更高的 `config.local.yaml` 保存个人设置。两个覆盖文件均由 Git 忽略。

```yaml
v: 5
laps: 100
routeConfig: "routes/XiXi.txt"
coordinateSystem: "bd09"
updateInterval: 1.0
```

`v` 是速度（米/秒），`laps` 是圈数（0–999 的整数），`updateInterval` 是更新间隔（0.1–10 秒）。桌面版已有路线记录时，会优先恢复最近使用的路线。

| 运行方式 | 配置文件位置 |
| --- | --- |
| 当前源码 | 项目根目录 |
| Windows / Linux 便携包 | 可执行文件所在目录 |
| macOS `.app` | `~/Library/Application Support/iOSRealRun/` |

相对路线路径以配置文件所在目录为准。内置路线也可直接填写文件名，例如 `XiXi.txt`，无需另行复制路线。

## 命令行

命令行支持 Windows / macOS，按配置的圈数运行。若要持续循环，在个人配置中设置 `laps: 0`。以下命令适用于当前 `main` 源码。

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

**兼容 iOS 26、27 和 iPadOS 26.4。** 这些系统的桌面连接需使用 USB 数据线，确认信任并开启开发者模式，无需手动挂载开发者磁盘镜像。旧版系统的桌面连接见下表。

| 其他设备系统 | 支持情况 |
| --- | --- |
| iOS / iPadOS 17.4–18.x | 已接入桌面连接流程，尚未完成逐版本真机验证。 |
| iOS / iPadOS 17.0–17.3 | 不支持当前连接方式。 |
| iOS / iPadOS 14–16 | 桌面 USB 直连，自动挂载本地匹配的开发者磁盘镜像；16 还需开发者模式。Windows + iOS 15.6 已获用户实测可用反馈，其他版本尚未完成真机回归。 |
| 低于 iOS / iPadOS 14 | 不支持。 |

Windows 11 x64 为当前开发和验证环境，Windows 10 x64 使用同一便携包。macOS 15+ / Apple Silicon、Ubuntu 22.04 / 24.04 x64 提供实验构建，已检查构建和界面启动，尚未完成 USB 真机回放验证。Windows ARM、Intel Mac 和其他 Linux 发行版暂无专门安装包。

### iOS 14-16 桌面连接

连接并解锁设备，确认信任后直接点击「开始模拟」。程序使用 USB 定位服务，不需要输入命令，也不需要启动隧道。iOS 14 / 15 没有开发者模式开关；iOS 16 仍需开启。

开始模拟或恢复定位时，程序先检查设备是否已挂载开发者镜像。已经挂载则直接复用；否则自动查找本地镜像并挂载。暂停、继续、停止及恢复定位与新版系统使用相同的界面。

本地镜像目录为 `DeveloperDiskImage/<系统版本>/`，每个版本目录中必须同时存在非空的 `DeveloperDiskImage.dmg` 和 `DeveloperDiskImage.dmg.signature`。例如 iOS 15.6 使用 `DeveloperDiskImage/15.6/`。可使用已有旧版工具中的对应镜像文件。

GitHub Release 安装包不内置 Apple 开发者镜像。Windows 上可将旧工具已有的 `15.6` 目录复制到新程序旁的 `DeveloperDiskImage` 目录，得到以下结构，然后重新点击「开始模拟」：

```text
iOSRealRun/
  iOSRealRun.exe
  _internal/
  DeveloperDiskImage/
    15.6/
      DeveloperDiskImage.dmg
      DeveloperDiskImage.dmg.signature
```

- Windows / Linux：将 `DeveloperDiskImage` 放在程序旁边。
- 源码启动：放在项目根目录。
- macOS 应用：放在 `~/Library/Application Support/iOSRealRun/` 下。

程序也会查找包内自带的镜像。优先匹配完整版本号，再匹配同一主、次版本（例如 15.6.1 可查找 15.6）；不会跨系统版本随意选用镜像。缺少镜像时，界面会给出要放置文件的完整目录。镜像挂载可通过「停止」取消，首次连接请保持设备解锁。

## 常见问题

**一直显示未连接设备**

Windows 先确认 Apple Devices / iTunes 能识别设备。检查数据线是否支持传输，解锁设备并确认信任，再点击「刷新」。开启开发者模式重启后，也需要重新解锁。

**找不到开发者模式开关**

如果设备是 iOS 14 / 15，无需此开关，直接按上方旧版系统说明连接。

先连接设备，在程序中点击「显示开发者模式开关」，然后前往设备的「设置 → 隐私与安全性」。开启后按提示重启并确认，详见 [Apple 开发者模式说明](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)。

**「开始模拟」不能点击**

检查设备栏提示、开发者模式和路线是否有效，以及速度和圈数下方的提示。未连接设备时仍可选路线、绘图和预览。

**不支持当前版本，或无法建立定位服务**

先对照[兼容性](#兼容性)，再重新连接设备，检查信任与开发者模式。提交 Issue 时附上完整系统版本和错误文本。

**位置出现整体偏移**

检查「坐标设置」是否与文件来源匹配。百度坐标应选择 BD-09，高德 / 腾讯选择 GCJ-02，GPS 选择 WGS 84。

**地图空白或只显示部分底图**

可在底图菜单切换到另一地图来源，或检查网络能否访问 OpenFreeMap 和 OpenStreetMap。未加载的区域稍后会自动重试，路线和模拟位置可继续显示。

**停止后定位没有恢复**

保持设备连接，重新打开程序并点击「恢复定位」。若设备服务仍无响应，可重启设备。恢复完成前不要拔线。

**源码启动提示 `No Python at ...`**

旧虚拟环境指向的 Python 可能已被删除或移动。启动器会备份失效环境并重建；请先安装 Python 3.12，必要时用 `Start-iOSRealRun.bat -Python "C:\path\to\python.exe"` 指定路径。
