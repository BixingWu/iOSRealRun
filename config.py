from pathlib import Path

import yaml

class Config:
    def __init__(self):
        root = Path(__file__).resolve().parent
        config = {}
        for name in ("config.yaml", "config.local.yaml"):
            path = root / name
            if path.is_file():
                values = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
                if not isinstance(values, dict):
                    raise ValueError(f"{name} 应包含键值配置。")
                config.update(values)
        if "routeConfig" in config:
            route = Path(config["routeConfig"])
            config["routeConfig"] = str(route if route.is_absolute() else root / route)
        for key, value in config.items():
            setattr(self, key, value)
