# 参与 iOSRealRun 开发

遇到问题先看 [README 的使用方法](README.md#使用方法)和[常见问题](README.md#常见问题)。如果仍能复现，请[提交问题报告](https://github.com/BixingWu/iOSRealRun-26/issues/new?template=bug_report.yml)，注明它发生在启动、设备连接、路线导入、回放还是恢复定位时。

## 本地开发

使用 Python 3.12，在项目目录创建独立环境。Windows 可运行 `.\Start-iOSRealRun.bat -SetupOnly`，以后使用 `.\.pvenv\Scripts\python.exe`。macOS 和 Linux 可执行以下命令。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python desktop.py
```

测试无需连接 iPhone 或 iPad。运行前将 `QT_QPA_PLATFORM` 设为 `offscreen`（PowerShell 用 `$env:QT_QPA_PLATFORM = "offscreen"`，Bash 或 Zsh 用 `export QT_QPA_PLATFORM=offscreen`）。用虚拟环境内的 Python 执行：

```sh
python -m unittest discover -s tests
python desktop.py --self-test
```

提交 PR 时说明用户会看到的变化、涉及的平台，以及实际运行过的测试。如果改的是打包或安装流程，请在目标系统上从生成的包启动一次，记录系统版本和 CPU 架构。

## 真机兼容性反馈

仅用自己有权测试的设备。反馈时写明电脑系统和架构、设备型号、完整的 iOS / iPadOS 版本、软件版本或提交号，以及使用的是发布包还是源码。若只有界面、自检或模拟设备测试，请按实际情况记录。

涉及设备的改动，能做真机测试时请记录 USB 识别、启动回放、暂停或停止、恢复定位分别是否成功。只贴相关错误和复现步骤，并遮盖截图中的设备名称、完整 UDID、序列号和个人位置。无需上传配对文件、个人轨迹、完整日志或本机配置。路线问题可用内置路线或几个无关位置的示例点复现。
