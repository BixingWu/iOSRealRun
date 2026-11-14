import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import qt_desktop as desktop


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        (self.root / "config.yaml").write_text(
            "v: 4.4\nrouteConfig: data/default.txt\ncoordinateSystem: bd09\n",
            encoding="utf-8-sig",
        )

    def test_cli_local_config_overrides_keys_and_resolves_the_route(self):
        (self.root / "config.local.yaml").write_text("v: 3.0\nrouteConfig: data/个人.txt\n", encoding="utf-8")
        with patch.object(config, "__file__", str(self.root / "config.py")):
            values = config.Config()
        self.assertEqual(values.v, 3.0)
        self.assertEqual(values.coordinateSystem, "bd09")
        self.assertEqual(Path(values.routeConfig), self.root / "data" / "个人.txt")

    def test_desktop_keeps_good_settings_when_local_config_is_malformed(self):
        (self.root / "config.local.yaml").write_text("[not, a, mapping]\n", encoding="utf-8")
        with patch.object(desktop, "ROOT", self.root):
            values, config_dir, warning = desktop.read_settings()
        self.assertEqual(config_dir, self.root)
        self.assertEqual(values["v"], 4.4)
        self.assertIn("config.local.yaml", warning)

    def test_portable_reads_config_and_local_override_next_to_executable(self):
        bundled = self.root / "_internal"
        bundled.mkdir()
        (bundled / "config.yaml").write_text("private_value: ignored\n", encoding="utf-8")
        (self.root / "config.local.yaml").write_text("v: 2.5\nrouteConfig: 路线.txt\n", encoding="utf-8")
        for platform, program in (("win32", "iOSRealRun.exe"), ("linux", "iOSRealRun")):
            with (
                self.subTest(platform=platform),
                patch.object(desktop, "ROOT", bundled),
                patch.object(desktop.sys, "platform", platform),
                patch.object(desktop.sys, "frozen", True, create=True),
                patch.object(desktop.sys, "executable", str(self.root / program)),
            ):
                values, config_dir, warning = desktop.read_settings()
                self.assertEqual(config_dir, self.root)
                self.assertEqual(values, {"v": 2.5, "routeConfig": "路线.txt", "coordinateSystem": "bd09"})
                self.assertFalse(warning)


if __name__ == "__main__":
    unittest.main()
