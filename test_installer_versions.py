"""Headless installation/version regressions; all files live in a temporary dir.

Run: python3 -m unittest discover -s data/mod_installer -p 'test_*.py'
"""

import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


# Importing the installer must not require Tk or create a window in CI.
tk = types.ModuleType("tkinter")
tk.ttk, tk.messagebox, tk.filedialog = Mock(), Mock(), Mock()
spec = importlib.util.spec_from_file_location(
    "installer_under_test", Path(__file__).with_name("pz_mod_installer.py"))
installer = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"tkinter": tk}):
    spec.loader.exec_module(installer)


class VersionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.app = installer.PZModInstaller.__new__(installer.PZModInstaller)
        self.app.mods_path = str(self.base / "mods")
        self.app.lua_dir = str(self.base / "Lua")
        self.app.state_file = str(self.base / "state.json")
        self.app.settings = dict(installer.launcher_config.DEFAULTS, modpack_url="https://example.invalid/modpack")
        self.app.root = Mock()
        self.app._log = Mock()
        self.app._pre_checks = Mock()
        self.app._finish = Mock()
        self.app._regen_modlist = Mock(return_value=(1, 1))
        self.app._total_bytes = 0
        (self.base / "mods" / "A").mkdir(parents=True)
        (self.base / "mods" / "A" / "old.txt").write_text("old")
        self.app._write_version(1)
        self.app._remember_managed(None, folders=["A", "Removed"])
        stopped = patch.object(installer.game_runtime, "ensure_game_stopped")
        stopped.start()
        self.addCleanup(stopped.stop)
        self.manifest = {
            "latest_version": 2,
            "versions": [{"version": 2, "changed": ["A", "B"], "removed": []}],
        }
        self.app._fetch_manifest = Mock(return_value=self.manifest)

    def archive(self, name, content):
        path = self.base / name
        with zipfile.ZipFile(path, "w") as zf:
            for member, text in content.items():
                zf.writestr(member, text)
        return path

    @staticmethod
    def missing():
        return urllib.error.HTTPError("https://test.invalid/mod.zip", 404, "missing", {}, None)

    def test_first_download_404_preserves_existing_install_and_version(self):
        self.app._download = Mock(side_effect=self.missing())
        with self.assertRaises(urllib.error.HTTPError):
            self.app._run_update()
        self.assertEqual(self.app._read_version(), 1)
        self.assertEqual((self.base / "mods/A/old.txt").read_text(), "old")
        self.app._finish.assert_not_called()

    def test_partial_update_download_failure_preserves_old_install_and_version(self):
        archive = self.archive("a.zip", {"A/new.txt": "new"})

        def download(url, dest, label):
            if url.endswith("A.zip"):
                shutil.copyfile(archive, dest)
            else:
                raise self.missing()

        self.app._download = download
        with self.assertRaises(urllib.error.HTTPError):
            self.app._run_update()
        self.assertEqual((self.base / "mods/A/old.txt").read_text(), "old")
        self.assertFalse((self.base / "mods/A/new.txt").exists())
        self.assertEqual(self.app._read_version(), 1)
        self.app._finish.assert_not_called()

    def test_manual_archive_never_inherits_server_latest_version(self):
        archive = self.archive("old-pack.zip", {"Old/mod.info": "id=Old"})
        self.app._run_manual(str(archive))
        self.assertTrue((self.base / "mods/Old/mod.info").is_file())
        self.assertIsNone(self.app._read_version())
        self.app._fetch_manifest.assert_not_called()
        self.app._full_install = Mock()
        self.app._run_update()
        self.app._full_install.assert_called_once_with(self.manifest)

    def test_full_install_without_manifest_clears_previous_version(self):
        archive = self.archive("full.zip", {"New/mod.info": "id=New"})
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        self.app._full_install(None)
        self.assertTrue((self.base / "mods/New/mod.info").is_file())
        self.assertIsNone(self.app._read_version())

    def test_extraction_failure_preserves_previous_install_and_version(self):
        archive = self.base / "corrupt.zip"
        archive.write_bytes(b"invalid zip")
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        with self.assertRaises(zipfile.BadZipFile):
            self.app._run_update()
        self.assertEqual(self.app._read_version(), 1)
        self.assertEqual((self.base / "mods/A/old.txt").read_text(), "old")
        self.app._finish.assert_not_called()

    def test_successful_update_records_version_after_all_mods_and_removals(self):
        self.manifest["versions"][0]["removed"] = ["Removed"]
        (self.base / "mods/Removed").mkdir()
        archives = {folder: self.archive(folder + ".zip", {folder + "/new.txt": folder})
                    for folder in ("A", "B")}

        def download(url, dest, label):
            folder = url.rsplit("/", 1)[1][:-4]
            shutil.copyfile(archives[folder], dest)

        self.app._download = download
        self.app._run_update()
        self.assertEqual(self.app._read_version(), 2)
        self.assertEqual((self.base / "mods/A/new.txt").read_text(), "A")
        self.assertEqual((self.base / "mods/B/new.txt").read_text(), "B")
        self.assertFalse((self.base / "mods/Removed").exists())
        self.app._finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
