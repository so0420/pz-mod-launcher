"""Workshop deletion tests operate only inside fresh temporary directories."""
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import workshop_cleanup as cleanup
import test_installer_versions as fixtures


class WorkshopCleanupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.libraries = [self.base / 'Steam', self.base / 'SteamLibrary']
        self.roots = [lib / cleanup.RELATIVE_ROOT for lib in self.libraries]
        for root in self.roots:
            mod = root / '12345' / 'mods' / 'Example'
            mod.mkdir(parents=True)
            (mod / 'mod.info').write_text('id=Example')
        self.stopped = patch.object(cleanup.game_runtime, 'ensure_game_stopped')
        self.stopped_mock = self.stopped.start()
        self.addCleanup(self.stopped.stop)

    def test_discovers_all_libraries_without_duplicate_targets(self):
        self.assertEqual(cleanup.find_workshop_roots(self.libraries + self.libraries), self.roots)
        with self.assertRaises(ValueError):
            cleanup.find_workshop_roots(['relative-library'])

    def test_removes_only_pz_workshop_content_and_keeps_other_files(self):
        kept = [self.roots[0].parent / '99999' / 'mod.txt',
                self.libraries[0] / 'steamapps/common/ProjectZomboid/game.txt',
                self.libraries[0] / 'steamapps/workshop/appworkshop_108600.acf',
                self.base / 'Zomboid/mods/Personal/mod.info',
                self.base / 'Zomboid/Saves/Multiplayer/Save/map.bin']
        for path in kept:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep')
        self.assertEqual(cleanup.remove_workshop(self.roots), self.roots)
        self.assertTrue(all(not root.exists() for root in self.roots))
        self.assertTrue(all(path.read_text() == 'keep' for path in kept))
        self.stopped_mock.assert_called_once()

    def test_invalid_later_target_preserves_every_cache(self):
        for bad in [self.roots[1].parent, self.roots[1].parent / '99999',
                    self.libraries[1], Path('steamapps/workshop/content/108600')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cleanup.remove_workshop([self.roots[0], bad])
            self.assertTrue(all(root.is_dir() for root in self.roots))

    def test_reparse_point_blocks_all_deletions_before_following_it(self):
        # Simulate the Windows junction attribute even without symlink privileges.
        original = Path.lstat
        blocked = self.roots[1].parents[1]

        def metadata(path):
            if path == blocked:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path)

        with patch.object(Path, 'lstat', metadata), self.assertRaises(ValueError):
            cleanup.remove_workshop(self.roots)
        self.assertTrue(all(root.is_dir() for root in self.roots))

    def test_nested_symlink_metadata_blocks_all_deletions(self):
        outside = self.base / 'Personal'
        outside.mkdir()
        (outside / 'keep.txt').write_text('keep')
        linked = self.roots[1] / 'linked'
        linked.mkdir()
        original = Path.lstat

        def metadata(path):
            if path == linked:
                return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original(path)

        with patch.object(Path, 'lstat', metadata), self.assertRaises(ValueError):
            cleanup.remove_workshop(self.roots)
        self.assertTrue(all(root.is_dir() for root in self.roots))
        self.assertEqual((outside / 'keep.txt').read_text(), 'keep')

    def test_game_started_during_confirmation_blocks_deletion(self):
        self.stopped_mock.side_effect = RuntimeError('game running')
        with self.assertRaises(RuntimeError):
            cleanup.remove_workshop(self.roots)
        self.assertTrue(all(root.is_dir() for root in self.roots))

    def test_readonly_files_are_removed(self):
        path = self.roots[0] / 'readonly.txt'
        path.write_text('cache')
        path.chmod(stat.S_IREAD)
        cleanup.remove_workshop([self.roots[0]])
        self.assertFalse(self.roots[0].exists())

    def test_locked_file_errors_are_not_ignored(self):
        error = PermissionError('locked')
        with patch.object(cleanup.shutil, 'rmtree', side_effect=error), self.assertRaises(PermissionError):
            cleanup.remove_workshop(self.roots)
        self.assertTrue(all(root.is_dir() for root in self.roots))

    def test_missing_and_duplicate_caches_are_safe(self):
        missing = self.base / 'Missing' / cleanup.RELATIVE_ROOT
        self.assertEqual(cleanup.remove_workshop([missing] + self.roots + self.roots), self.roots)


class WorkshopWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / 'Steam' / cleanup.RELATIVE_ROOT
        (self.root / '12345').mkdir(parents=True)
        self.app = fixtures.installer.PZModInstaller.__new__(fixtures.installer.PZModInstaller)
        self.app.settings = dict(fixtures.installer.launcher_config.DEFAULTS)
        self.app.steam_libraries = [self.base / 'Steam']
        self.app.root = Mock()
        self.app._set_check = Mock()
        self.app._log = Mock()
        self.app._ask_on_main = Mock(return_value=False)
        stopped = patch.object(cleanup.game_runtime, 'ensure_game_stopped')
        stopped.start()
        self.addCleanup(stopped.stop)

    def test_disabled_option_does_not_ask_or_delete(self):
        self.app._step_check_workshop()
        self.assertTrue(self.root.is_dir())
        self.app._ask_on_main.assert_not_called()

    def test_cancel_aborts_launch_before_update_or_java(self):
        self.app.settings['force_workshop_delete'] = True
        self.app._step_check_steam = Mock()
        self.app._step_check_pz = Mock()
        self.app._run_update = Mock()
        with patch.object(fixtures.installer.game_launch, 'launch_game') as launch, \
                self.assertRaises(fixtures.installer._AbortInstall):
            self.app._run_launch()
        self.assertTrue(self.root.is_dir())
        self.app._run_update.assert_not_called()
        launch.assert_not_called()

    def test_confirmed_option_shows_target_then_deletes(self):
        self.app.settings['force_workshop_delete'] = True
        self.app._ask_on_main.side_effect = lambda callback: callback()
        with patch.object(fixtures.installer.messagebox, 'askyesno', return_value=True) as confirm:
            self.app._step_check_workshop()
        self.assertIn(str(self.root), confirm.call_args.args[1])
        self.assertEqual(confirm.call_args.kwargs['default'], 'no')
        self.assertFalse(self.root.exists())
        self.app._set_check.assert_called_with('workshop', 'ok')

    def test_manual_game_folder_still_discovers_steam_when_option_enabled(self):
        self.app.settings.update(game_path=str(self.base / 'game'), force_workshop_delete=True)
        self.app._step_check_steam = Mock()
        self.app._step_check_pz = Mock()
        self.app._step_check_workshop = Mock()
        self.app._pre_checks()
        self.app._step_check_steam.assert_called_once()
        self.app._step_check_workshop.assert_called_once()

    def test_manual_game_folder_without_option_does_not_require_steam(self):
        self.app.settings['game_path'] = str(self.base / 'game')
        self.app._step_check_steam = Mock()
        self.app._step_check_pz = Mock()
        self.app._step_check_workshop = Mock()
        self.app._pre_checks()
        self.app._step_check_steam.assert_not_called()

    def test_delete_failure_aborts_install_and_marks_check_failed(self):
        self.app.settings['force_workshop_delete'] = True
        self.app._ask_on_main.return_value = True
        with patch.object(fixtures.installer.workshop_cleanup, 'remove_workshop', side_effect=PermissionError('locked')), \
                self.assertRaises(PermissionError):
            self.app._step_check_workshop()
        self.assertTrue(self.root.exists())
        self.app._set_check.assert_called_with('workshop', 'fail')

    def test_no_cache_does_not_ask_for_confirmation(self):
        self.app.settings['force_workshop_delete'] = True
        self.app.steam_libraries = [self.base / 'Missing']
        self.app._step_check_workshop()
        self.app._ask_on_main.assert_not_called()
        self.app._set_check.assert_called_with('workshop', 'ok')


if __name__ == '__main__':
    unittest.main()
