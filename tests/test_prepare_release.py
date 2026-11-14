import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / ".github/prepare_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.downloads = directory / "incoming-artifacts"
        self.downloads.mkdir()
        self.output = directory / "release-assets"

    def write_asset(self, name, data, parent="."):
        directory = self.downloads / parent
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)

    def test_stages_exact_names_and_hashes_from_nested_downloads(self):
        payloads = (b"windows", b"mac" * 360_000, b"linux")
        parents = ("iOSRealRun-Windows-x64/windows-x64-id", "macos-arm64-id", ".")
        for name, data, parent in zip(MODULE.ASSETS, payloads, parents):
            self.write_asset(name, data, parent)
            self.write_asset(f"{name}.bak", b"ignored", parent)

        MODULE.prepare_release(self.downloads, self.output)

        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         sorted((*MODULE.ASSETS, "SHA256SUMS.txt")))
        for name, data in zip(MODULE.ASSETS, payloads):
            self.assertEqual((self.output / name).read_bytes(), data)
        expected = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                           for name, data in zip(MODULE.ASSETS, payloads))
        self.assertEqual((self.output / "SHA256SUMS.txt").read_bytes(), expected.encode("ascii"))

    def test_duplicate_is_rejected_before_staging(self):
        for name in MODULE.ASSETS:
            self.write_asset(name, b"archive", "one")
        self.write_asset(MODULE.ASSETS[0], b"other archive", "two")

        with self.assertRaisesRegex(ValueError, r"Found 2: one/.*two/"):
            MODULE.prepare_release(self.downloads, self.output)

        self.assertFalse(self.output.exists())

    def test_missing_is_rejected_before_staging(self):
        for name in MODULE.ASSETS[:-1]:
            self.write_asset(name, b"archive", "nested")

        with self.assertRaisesRegex(ValueError, r"Linux-x64.tar.gz.*Found 0"):
            MODULE.prepare_release(self.downloads, self.output)

        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
