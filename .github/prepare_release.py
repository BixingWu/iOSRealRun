"""Stage uploaded platform archives and write a SHA-256 manifest."""

import argparse
import hashlib
import shutil
from pathlib import Path


ASSETS = (
    "iOSRealRun-Windows-x64.zip",
    "iOSRealRun-macOS-arm64.zip",
    "iOSRealRun-Linux-x64.tar.gz",
)


def prepare_release(downloads, output):
    if not downloads.is_dir():
        raise ValueError(f"Artifact download directory does not exist: {downloads}")

    sources = {}
    for name in ASSETS:
        matches = sorted(path for path in downloads.rglob(name) if path.name == name)
        if len(matches) != 1:
            paths = ", ".join(path.relative_to(downloads).as_posix() for path in matches) or "none"
            raise ValueError(f"Expected exactly one {name} under {downloads}. Found {len(matches)}: {paths}")
        source = matches[0]
        if source.is_symlink() or not source.is_file() or not source.stat().st_size:
            raise ValueError(f"Expected a nonempty archive file: {source}")
        sources[name] = source

    output.mkdir()
    with (output / "SHA256SUMS.txt").open("w", encoding="ascii", newline="\n") as manifest:
        for name, source in sources.items():
            staged = output / name
            shutil.copyfile(source, staged)
            digest = hashlib.sha256()
            with staged.open("rb") as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    digest.update(chunk)
            manifest.write(f"{digest.hexdigest()}  {name}\n")
            print(f"Staged {source.relative_to(downloads).as_posix()} as {staged}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("downloads", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        prepare_release(args.downloads, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot prepare release assets: {error}\n")


if __name__ == "__main__":
    main()
