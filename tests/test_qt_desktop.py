import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QPlainTextEdit, QPushButton

from iosrealrun.app_version import VERSION
from iosrealrun.desktop_device import Device
from iosrealrun.config import read_settings
from iosrealrun.paths import RESOURCE_ROOT
from iosrealrun.qt_desktop import Desktop, main


class DesktopUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyle("Fusion")
        cls.application.setQuitOnLastWindowClosed(False)

    def make_window(self):
        with patch("iosrealrun.qt_desktop.read_settings", return_value=({}, RESOURCE_ROOT, "")):
            window = Desktop(discover=False)
        window.show()
        self.application.processEvents()
        self.addCleanup(window.close)
        return window

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.application.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail("The desktop did not finish the operation.")

    def test_no_device_keeps_route_controls_available(self):
        window = self.make_window()
        self.assertIsNone(window.selected_device())
        self.assertEqual(window.device_box.currentText(), "未连接设备")
        self.assertFalse(window.start_button.isEnabled())
        self.assertFalse(window.device_box.isEnabled())
        self.assertTrue(window.map_button.isEnabled())
        self.assertTrue(window.import_button.isEnabled())

    def test_editor_and_preview_share_style_without_changing_route(self):
        window = self.make_window()
        route = list(window.display_points)
        style_box = window.map_style_box
        style_box.setCurrentIndex(style_box.findData("dark"))
        picker = window.pick_route()
        self.application.processEvents()
        editor_box = next(box for box in picker.findChildren(QComboBox) if box.findData("light") >= 0)
        self.assertEqual(editor_box.currentData(), "dark")
        editor_box.setCurrentIndex(editor_box.findData("street"))
        picker.reject()
        self.assertEqual(style_box.currentData(), "street")
        self.assertEqual(window.display_points, route)

    def test_bundled_route_stays_closed_when_its_file_resolves_to_resources(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            contents = Path(directory).resolve() / "iOSRealRun.app" / "Contents"
            framework_root = contents / "Frameworks"
            resource_root = contents / "Resources"
            (framework_root / "routes").mkdir(parents=True)
            (resource_root / "routes").mkdir(parents=True)
            preset = framework_root / "routes" / "ZJGEast.txt"
            target = resource_root / "routes" / preset.name
            route = '[{"lat": 30.1, "lng": 120.1}, {"lat": 30.101, "lng": 120.101}]'
            preset.write_text(route, encoding="utf-8")
            target.write_text(route, encoding="utf-8")
            custom = contents / preset.name
            custom.write_text(route, encoding="utf-8")
            resolve = type(preset).resolve

            def resolve_bundle_path(path, *args, **kwargs):
                return target if path == preset else resolve(path, *args, **kwargs)

            # Emulate the file symlink on Windows runners without symlink privileges.
            with (
                patch("iosrealrun.paths.RESOURCE_ROOT", framework_root),
                patch.object(type(preset), "resolve", resolve_bundle_path),
            ):
                self.assertTrue(window.open_route(preset, remember=False))
                self.assertEqual(window.route_box.currentText(), "紫金港东操场")
                self.assertTrue(window.closed.isChecked())
                window.laps.setText("0")
                self.assertEqual(window.duration_text.text(), "持续")
                self.assertTrue(window.open_route(custom, remember=False))
                self.assertFalse(window.closed.isChecked())
                self.assertEqual(window.route_box.currentText(), custom.name)

    def test_version_command_does_not_create_a_window(self):
        output = io.StringIO()
        with patch("sys.argv", ["iosrealrun", "--version"]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_status:
                main()
        self.assertEqual(exit_status.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"iOSRealRun {VERSION}")

    def test_macos_bundle_reads_user_config_outside_signed_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            user_config = home / "Library" / "Application Support" / "iOSRealRun"
            user_config.mkdir(parents=True)
            (user_config / "config.yaml").write_text('routeConfig: "测试.gpx"\nv: 3.1\n', encoding="utf-8")
            with (
                patch("sys.platform", "darwin"),
                patch("sys.frozen", True, create=True),
                patch("sys.executable", str(home / "iOSRealRun.app" / "Contents" / "MacOS" / "iOSRealRun")),
                patch.object(Path, "home", return_value=home),
                patch("iosrealrun.paths.RESOURCE_ROOT", home / "iOSRealRun.app" / "Contents" / "Frameworks"),
            ):
                settings, config_dir, warning = read_settings()
        self.assertEqual(config_dir, user_config)
        self.assertEqual(settings, {"routeConfig": "测试.gpx", "v": 3.1})
        self.assertEqual(warning, "")

    def test_duplicate_device_selection_survives_rescan(self):
        window = self.make_window()
        first = Device("first-1234", "iPhone", "27.0", True)
        second = Device("second-1234", "iPhone", "27.0", True)
        window.receive("scan", True, [first, second])
        window.device_box.setCurrentIndex(1)
        labels = {window.device_box.itemText(index) for index in range(window.device_box.count())}
        self.assertEqual(len(labels), 2)
        window.receive("scan", True, [second, first])
        self.assertEqual(window.selected_device(), second)

    def test_parameter_validation_and_open_route(self):
        window = self.make_window()
        window.receive("scan", True, [Device("valid", "iPhone", "26.0", True)])
        self.assertTrue(window.start_button.isEnabled())
        for value in ("nan", "Inf", "0", "31", "bad"):
            with self.subTest(speed=value):
                window.speed.setText(value)
                self.assertTrue(window.speed.property("error"))
                self.assertFalse(window.start_button.isEnabled())
        window.speed.setText("4.2")
        window.laps.setText("1.25")
        self.assertFalse(window.start_button.isEnabled())
        window.closed.setChecked(False)
        self.assertEqual(window.laps.text(), "1")
        self.assertFalse(window.laps.isEnabled())
        self.assertTrue(window.start_button.isEnabled())
        window.interval = "nan"
        window.update_controls()
        self.assertFalse(window.start_button.isEnabled())

    def test_ios156_can_start_and_reset_without_showing_developer_mode_action(self):
        window = self.make_window()
        window.receive("scan", True, [Device("legacy", "iPhone", "15.6")])
        self.assertTrue(window.start_button.isEnabled())
        self.assertTrue(window.reset_button.isVisible())
        self.assertFalse(window.device_action.isVisible())
        self.assertNotIn("命令行", window.device_detail.text())
        # Starting from the UI must actually submit a replay, not just enable
        # the button while leaving the old developer-mode guard in place.
        with patch.object(window, "submit") as submit:
            window.start_or_stop()
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[0], "replay")
            submit.call_args.args[1].close()

    def test_ios16_disabled_developer_mode_keeps_start_disabled(self):
        window = self.make_window()
        window.receive("scan", True, [Device("legacy", "iPhone", "16.7", False, "请开启开发者模式")])
        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.device_action.isVisible())
        self.assertEqual(window.device_action.text(), "显示开发者模式开关")

    def test_route_restores_coordinate_system_and_closure(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as folder:
            window.route_store = Path(folder) / "last-route.json"
            points = [{"lat": 30.1, "lng": 120.1}, {"lat": 30.101, "lng": 120.101}]
            window.set_route(points, "地图路线", "wgs84", False)
            with patch("iosrealrun.qt_desktop.read_settings", return_value=({}, RESOURCE_ROOT, "")):
                window.load_settings()
            self.assertEqual(window.points, points)
            self.assertEqual(window.route_box.currentText(), "地图路线")
            self.assertEqual(window.system_box.currentData(), "wgs84")
            self.assertFalse(window.closed.isChecked())

    def test_paste_dialog_uses_explicit_coordinate_system(self):
        window = self.make_window()
        window.select_system("wgs84")
        window.paste_button.click()
        self.application.processEvents()
        dialog = next(dialog for dialog in window.findChildren(QDialog) if dialog.isVisible())
        system_box = dialog.findChild(QComboBox)
        self.assertEqual(system_box.currentData(), "bd09")
        system_box.setCurrentIndex(system_box.findData("gcj02"))
        dialog.findChild(QPlainTextEdit).setPlainText('[{"lat": 30.1, "lng": 120.1}, {"lat": 30.101, "lng": 120.101}]')
        next(button for button in dialog.findChildren(QPushButton) if button.text() == "使用路线").click()
        self.application.processEvents()
        self.assertEqual(window.route_box.currentText(), "粘贴的路线")
        self.assertEqual(window.system_box.currentData(), "gcj02")
        self.assertFalse(window.closed.isChecked())

    def test_close_waits_for_background_replay_cleanup(self):
        window = self.make_window()
        window.receive("scan", True, [Device("valid", "iPhone", "26.0", True)])
        started = threading.Event()
        cleaned = threading.Event()

        async def replay(*args, stop_requested, on_progress, **kwargs):
            import asyncio

            on_progress(1, 0.1, window.display_points[0])
            started.set()
            while not stop_requested():
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.03)
            cleaned.set()
            return True

        with patch("iosrealrun.qt_desktop.replay_route", replay):
            window.start_or_stop()
            self.wait_for(lambda: started.is_set() and window.pause_button.isVisible())
            self.assertEqual(window.map_state.text(), "实时位置")
            window.toggle_pause()
            self.assertTrue(window.paused.is_set())
            self.assertEqual(window.map_state.text(), "模拟已暂停")
            window.close()
            self.assertTrue(window.isVisible())
            self.assertTrue(window.closing)
            self.assertTrue(window.stop.is_set())
            self.wait_for(lambda: not window.isVisible())
        self.assertTrue(cleaned.is_set())

    def test_compact_view_keeps_fixed_controls_and_reveals_advanced(self):
        window = self.make_window()
        window.resize(window.minimumSize())
        self.application.processEvents()
        for control in (window.start_button, window.map_button):
            self.assertTrue(control.isVisible())
            self.assertTrue(window.rect().contains(control.mapTo(window, control.rect().bottomRight())))
        self.assertFalse(window.controls.verticalScrollBar().isVisible())
        window.advanced_button.click()
        window.system_box.setFocus()
        self.application.processEvents()
        self.assertTrue(window.system_box.isVisible())
        corner = window.system_box.mapTo(window.controls.viewport(), window.system_box.rect().bottomRight())
        self.assertTrue(window.controls.viewport().rect().contains(corner))
