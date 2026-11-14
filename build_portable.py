"""Build and smoke-test a portable archive on the target operating system."""

import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT = Path(__file__).resolve().parent
APP_NAME = "iOSRealRun"
TARGETS = {
    ("win32", "win-amd64"): ("windows-x64", "Windows-x64.zip"),
    ("darwin", "arm64"): ("macos-arm64", "macOS-arm64.zip"),
    ("linux", "x86_64"): ("linux-x64", "Linux-x64.tar.gz"),
}


def run(command, *, timeout=None, env=None):
    subprocess.run(command, cwd=PROJECT, check=True, timeout=timeout, env=env)


def build_environment():
    env = os.environ.copy()
    if sys.platform == "win32":
        # Avoid collecting unrelated DLLs from tools on the user's PATH. In
        # particular, third-party ICU builds cannot replace Windows' ICU API.
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        search = (Path(sys.executable).parent, Path(sys.base_prefix),
                  Path(sys.base_prefix) / "DLLs", windows / "System32", windows)
        env["PATH"] = os.pathsep.join(str(path) for path in search)
    return env


def include_documentation(directory):
    for name in ("LICENSE", "README.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(PROJECT / name, directory)
    shutil.copytree(PROJECT / "LICENSES", directory / "LICENSES")
    shutil.copytree(PROJECT / "docs", directory / "docs")


def smoke_test(package):
    executable = package / APP_NAME
    if sys.platform == "win32":
        executable = executable.with_suffix(".exe")
        plugins = package / "_internal/PySide6/plugins/platforms"
        native_plugin, offscreen_plugin = "qwindows.dll", "qoffscreen.dll"
    elif sys.platform == "darwin":
        executable = package / "Contents/MacOS" / APP_NAME
        plugins = package / "Contents/Frameworks/PySide6/Qt/plugins/platforms"
        native_plugin, offscreen_plugin = "libqcocoa.dylib", "libqoffscreen.dylib"
        run(["codesign", "--verify", "--deep", "--strict", str(package)])
    else:
        plugins = package / "_internal/PySide6/Qt/plugins/platforms"
        native_plugin, offscreen_plugin = "libqxcb.so", "libqoffscreen.so"

    for name in (native_plugin, offscreen_plugin):
        if not (plugins / name).is_file():
            raise RuntimeError(f"The packaged Qt platform plugin {name} was not found at {plugins}.")
    run([str(executable), "--self-test"], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=60)
    if sys.platform == "linux" and shutil.which("xvfb-run"):
        run(["xvfb-run", "-a", str(executable), "--self-test"],
            env={**os.environ, "QT_QPA_PLATFORM": "xcb"}, timeout=60)


def main():
    machine = sysconfig.get_platform() if sys.platform == "win32" else platform.machine()
    if sys.version_info[:2] != (3, 12) or (sys.platform, machine) not in TARGETS:
        raise SystemExit("Use native Python 3.12 on Windows x64, macOS arm64, or Linux x64.")
    directory_name, filename = TARGETS[sys.platform, machine]
    dist = PROJECT / "dist"
    dist.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{directory_name}-", dir=dist))
    run([sys.executable, "-I", "-m", "PyInstaller", "--noconfirm",
         "--distpath", str(directory), "--workpath", str(directory / "work"), str(PROJECT / "iosrealrun.spec")],
        env=build_environment())

    archive = directory / f"{APP_NAME}-{filename}"
    package = directory / (f"{APP_NAME}.app" if sys.platform == "darwin" else APP_NAME)
    smoke_test(package)

    if sys.platform == "darwin":
        # Ship the documentation beside the signed bundle and preserve framework symlinks.
        payload = directory / "payload" / APP_NAME
        payload.mkdir(parents=True)
        package.rename(payload / package.name)
        include_documentation(payload)
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(payload), str(archive)])
    else:
        include_documentation(package)
        if sys.platform == "win32":
            with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as output:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        output.write(path, path.relative_to(directory))
        else:
            with tarfile.open(archive, "w:gz") as output:
                output.add(package, arcname=package.name)
    print(f"Portable package: {archive}", flush=True)


if __name__ == "__main__":
    main()
