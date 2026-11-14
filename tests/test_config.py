import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iosrealrun import config, paths


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        (self.root / "config.example.yaml").write_text(
            "v: 4.4\nrouteConfig: data/default.txt\ncoordinateSystem: bd09\n",
            encoding="utf-8-sig",
        )

    def test_cli_local_config_overrides_keys_and_resolves_the_route(self):
        (self.root / "config.local.yaml").write_text("v: 3.0\nrouteConfig: data/个人.txt\n", encoding="utf-8")
        (self.root / "config.yaml").write_text("v: 3.8\ncoordinateSystem: gcj02\n", encoding="utf-8")
        with patch.object(paths, "RESOURCE_ROOT", self.root):
            values = config.Config()
        self.assertEqual(values.v, 3.0)
        self.assertEqual(values.coordinateSystem, "gcj02")
        self.assertEqual(Path(values.routeConfig), self.root / "data" / "个人.txt")

    def test_desktop_keeps_good_settings_when_local_config_is_malformed(self):
        (self.root / "config.local.yaml").write_text("[not, a, mapping]\n", encoding="utf-8")
        with patch.object(paths, "RESOURCE_ROOT", self.root):
            values, config_dir, warning = config.read_settings()
        self.assertEqual(config_dir, self.root)
        self.assertEqual(values["v"], 4.4)
        self.assertIn("config.local.yaml", warning)

    def test_portable_reads_config_and_local_override_next_to_executable(self):
        bundled = self.root / "_internal"
        bundled.mkdir()
        (bundled / "config.example.yaml").write_text("coordinateSystem: bd09\nv: 4.4\n", encoding="utf-8")
        (bundled / "config.yaml").write_text("private_value: ignored\n", encoding="utf-8")
        (self.root / "config.local.yaml").write_text("v: 2.5\nrouteConfig: 路线.txt\n", encoding="utf-8")
        for platform, program in (("win32", "iOSRealRun.exe"), ("linux", "iOSRealRun")):
            with (
                self.subTest(platform=platform),
                patch.object(paths, "RESOURCE_ROOT", bundled),
                patch.object(paths.sys, "platform", platform),
                patch.object(paths.sys, "frozen", True, create=True),
                patch.object(paths.sys, "executable", str(self.root / program)),
            ):
                values, config_dir, warning = config.read_settings()
                self.assertEqual(config_dir, self.root)
                self.assertEqual(values, {"v": 2.5, "routeConfig": "路线.txt", "coordinateSystem": "bd09"})
                self.assertFalse(warning)

    def test_legacy_preset_path_resolves_without_shadowing_same_name_custom_route(self):
        routes = self.root / "routes"
        routes.mkdir()
        bundle_preset = routes / "YuQuan.txt"
        bundle_preset.write_text("preset", encoding="utf-8")
        (self.root / "config.local.yaml").write_text("routeConfig: YuQuan.txt\n", encoding="utf-8")
        with patch.object(paths, "RESOURCE_ROOT", self.root):
            self.assertEqual(Path(config.Config().routeConfig), bundle_preset)
            custom = self.root / "YuQuan.txt"
            custom.write_text("custom", encoding="utf-8")
            self.assertEqual(Path(config.Config().routeConfig), custom)
            self.assertEqual(paths.resolve_route("my-routes/YuQuan.txt", self.root), self.root / "my-routes/YuQuan.txt")


if __name__ == "__main__":
    unittest.main()
