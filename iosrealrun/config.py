import yaml

from iosrealrun import paths


DEFAULT_SPEED = 5
DEFAULT_LAPS = 100


def read_settings(*, strict=False):
    config_dir = paths.config_directory()
    settings, warnings = {}, []
    for path in (paths.RESOURCE_ROOT / "config.example.yaml", config_dir / "config.yaml",
                 config_dir / "config.local.yaml"):
        try:
            values = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if not isinstance(values, dict):
                raise ValueError(f"{path.name} 应包含键值配置。")
            settings.update(values)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, yaml.YAMLError):
            if strict:
                raise
            warnings.append(f"{path.name} 无法读取，已使用其余可用设置。")
    return settings, config_dir, " ".join(warnings)


class Config:
    def __init__(self):
        settings, config_dir, _ = read_settings(strict=True)
        if "routeConfig" in settings:
            settings["routeConfig"] = str(paths.resolve_route(settings["routeConfig"], config_dir))
        for key, value in settings.items():
            setattr(self, key, value)
