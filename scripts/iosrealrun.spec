import os
import re
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata, get_package_paths


scripts = Path(SPECPATH)
project = scripts.parent
version = runpy.run_path(str(project / "iosrealrun/app_version.py"))["VERSION"]
build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
revision = os.environ.get("IOSREALRUN_BUILD_REVISION") or os.environ.get("GITHUB_SHA", "")
if re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
    build_id += "-" + revision[:10].lower()
build_hook = Path(workpath) / "iosrealrun_build_id.py"
build_hook.write_text(f"import sys\nsys._iosrealrun_build_id = {build_id!r}\n", encoding="utf-8")
print(f"iOSRealRun build: {build_id}", flush=True)
route_files = ("ZJGEast.txt", "ZJGWest.txt", "YuQuan.txt", "HaiNing.txt", "XiXi.txt")
data = [(str(project / "routes" / filename), "routes") for filename in route_files]
data += [(str(project / "config.example.yaml"), ".")]
# Local compatibility builds can include images already supplied by the user.
# These Apple assets are optional and are not tracked in the source repository.
legacy_images = project / "DeveloperDiskImage"
if legacy_images.is_dir():
    data += [(str(legacy_images), "DeveloperDiskImage")]
# Preserve dependency notices. Some device dependencies also query metadata at runtime.
data += copy_metadata("pymobiledevice3", recursive=True)
data += copy_metadata("geopy", recursive=True)
data += copy_metadata("PyYAML")
data += copy_metadata("PySide6-Essentials", recursive=True)
data += copy_metadata("mapbox-vector-tile", recursive=True)
data += collect_data_files("pymobiledevice3", subdir="resources")

binaries = []
icon = None
if sys.platform == "win32":
    # Importing the userspace tunnel also loads Wintun on Windows.
    wintun = Path(get_package_paths("pytun_pmd3")[1]) / "wintun"
    data += [(str(wintun / "LICENSE.txt"), "pytun_pmd3/wintun")]
    binaries += [(str(wintun / "bin" / "amd64" / "wintun.dll"), "pytun_pmd3/wintun/bin/amd64")]
    qt_root = Path(get_package_paths("PySide6")[1])
    vc_runtime = {name: qt_root / name for name in ("vcruntime140.dll", "vcruntime140_1.dll")}
    for path in vc_runtime.values():
        if not path.is_file():
            raise FileNotFoundError(f"Qt's Visual C++ runtime DLL was not found: {path}")
    icon = str(project / "assets" / "app.ico")

analysis = Analysis(
    [str(scripts / "desktop_entry.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=data,
    runtime_hooks=[str(build_hook)],
    hiddenimports=[
        "pymobiledevice3.remote.userspace_tunnel",
        # PyInstaller's PySide6 hook checks for the optional meta-distribution.
        "PySide6.support.deprecated",
    ],
    excludes=["tkinter"],
)
if sys.platform == "win32":
    # Windows 10+ supplies the UCRT and ICU implementations that Qt expects.
    # An unrelated ICU from the build machine can shadow those APIs at runtime.
    windows_dll = re.compile(r"(?:icu(?:dt|in|uc)?\d*|ucrtbase|api-ms-win-.*|ext-ms-win-.*)\.dll", re.I)
    analysis.binaries = [
        (destination, str(vc_runtime.get(Path(destination).name.lower(), source)), kind)
        for destination, source, kind in analysis.binaries
        if not windows_dll.fullmatch(Path(destination).name)
    ]
    # Python loads from the bundle root before Qt imports its own runtime DLLs.
    existing_runtime = {destination.lower() for destination, _, _ in analysis.binaries}
    analysis.binaries.extend(
        (name, str(path), "BINARY") for name, path in vc_runtime.items() if name not in existing_runtime
    )
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="iOSRealRun",
    icon=icon,
    console=sys.platform == "linux" or os.environ.get("IOSREALRUN_BUILD_CONSOLE") == "1",
    upx=False,
)
app = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    upx=False,
    name="iOSRealRun",
)

if sys.platform == "darwin":
    desktop_version = version.split("-", 1)[0]
    app = BUNDLE(
        app,
        name="iOSRealRun.app",
        icon=str(project / "assets" / "app.icns"),
        bundle_identifier="com.github.BixingWu.iOSRealRun",
        version=desktop_version,
        info_plist={"CFBundleVersion": desktop_version, "LSMinimumSystemVersion": "15.0"},
    )
