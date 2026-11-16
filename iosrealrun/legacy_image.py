"""Find locally supplied developer images for iOS 14–16 without a CLI or download."""

from iosrealrun.driver.connect import device_version
from iosrealrun.paths import RESOURCE_ROOT, config_directory


def _image_versions(version):
    number = device_version(version)
    if number is None or not (14, 0) <= number < (17, 0):
        return ()
    # Prefer an exact patch release; then use the same major/minor image, as
    # Xcode and pymobiledevice3 do. Never pick an unrelated iOS image.
    exact = version.strip().split()[0]
    return tuple(dict.fromkeys((exact, f"{number[0]}.{number[1]}")))


def legacy_image_directory(version):
    versions = _image_versions(version)
    if not versions:
        raise ValueError("开发者镜像仅适用于 iOS 14–16。")
    return config_directory() / "DeveloperDiskImage" / versions[-1]


def find_legacy_image(version):
    roots = tuple(dict.fromkeys((config_directory(), RESOURCE_ROOT)))
    for name in _image_versions(version):
        for root in roots:
            directory = root / "DeveloperDiskImage" / name
            image = directory / "DeveloperDiskImage.dmg"
            signature = directory / "DeveloperDiskImage.dmg.signature"
            if image.is_file() and signature.is_file() and image.stat().st_size and signature.stat().st_size:
                return image, signature
    return None
