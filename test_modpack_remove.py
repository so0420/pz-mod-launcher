from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import modpack_remove as remove


class RemoveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.mods = self.base / 'mods'
        self.pack = self.mods / 'Pack/42'
        self.pack.mkdir(parents=True)
        (self.pack / 'mod.info').write_text('id=Owned\n', encoding='utf-8')
        self.personal = self.mods / 'Personal'
        self.personal.mkdir()
        (self.personal / 'mod.info').write_text('id=Personal\n', encoding='utf-8')
        self.lua = self.base / 'Lua'
        self.lua.mkdir()
        self.modlist = self.lua / 'modmanager-mods.txt'
        self.modlist.write_bytes(b'\xef\xbb\xbfVERSION=1\r\nOwned;Personal;Other\r\n')
        self.state = self.base / 'records/state.json'
        self.state.parent.mkdir()
        self.state.write_text('{"version":1}')
        self.managed = self.state.parent / '_modpack_managed.json'
        self.managed.write_text('{"folders":["Pack"]}')
        self.game = self.base / 'game'
        self.game.mkdir()
        (self.game / 'ProjectZomboid64.json').write_bytes(b'user game config')
        (self.game / 'patch.jar').write_bytes(b'user patch')
        self.save = self.base / 'Saves/map.bin'
        self.save.parent.mkdir()
        self.save.write_bytes(b'precious save')
        stopped = patch.object(remove.runtime, 'ensure_game_stopped')
        stopped.start()
        self.addCleanup(stopped.stop)

    def run_remove(self, folders=None):
        return remove.remove_modpack(self.game, self.mods, self.lua, self.state,
                                     ['Pack'] if folders is None else folders)

    def test_removes_owned_mods_preserving_personal_mods_saves_and_game_patches(self):
        self.assertEqual(self.run_remove(), {'removed': ['Pack'], 'keptcount': 1})
        self.assertTrue(self.personal.exists())
        self.assertEqual(self.modlist.read_bytes(), b'\xef\xbb\xbfVERSION=1\r\nPersonal;Other\r\n')
        self.assertEqual(self.save.read_bytes(), b'precious save')
        self.assertEqual((self.game / 'patch.jar').read_bytes(), b'user patch')
        self.assertEqual((self.game / 'ProjectZomboid64.json').read_bytes(), b'user game config')
        self.assertFalse(self.state.exists())
        self.assertFalse(self.managed.exists())

    def test_bad_folder_names_are_rejected_before_mutation(self):
        for names in [['../Pack'], ['C:Pack'], ['Pack.'], ['NUL'], 'Pack']:
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.run_remove(names)
        self.assertTrue(self.pack.exists())

    def test_write_failure_restores_mods_and_all_metadata(self):
        original = self.modlist.read_bytes()
        write = remove.runtime._atomic_write
        calls = 0
        def fail_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('disk full')
            return write(path, data)
        with patch.object(remove.runtime, '_atomic_write', side_effect=fail_once), self.assertRaises(OSError):
            self.run_remove()
        self.assertTrue(self.pack.exists())
        self.assertTrue(self.state.exists())
        self.assertEqual(self.modlist.read_bytes(), original)

    def test_failed_rollback_preserves_disk_backup(self):
        replace = remove.os.replace
        def fail_restore(src, dst):
            if '.pz-remove-backup-' in str(src):
                raise OSError('restore failed')
            return replace(src, dst)
        with patch.object(remove.runtime, '_atomic_write', side_effect=OSError('disk full')), \
                patch.object(remove.os, 'replace', side_effect=fail_restore), self.assertRaisesRegex(RuntimeError, '복구 백업:'):
            self.run_remove()
        backups = list(self.base.glob('.pz-remove-backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / 'mods/Pack/42/mod.info').exists())
        self.assertTrue((backups[0] / 'restore.json').exists())

    def test_shared_id_keeps_personal_activation(self):
        (self.personal / 'mod.info').write_text('id=Owned\n', encoding='utf-8')
        self.run_remove()
        self.assertIn(b'Owned', self.modlist.read_bytes())

    def test_running_game_blocks_removal(self):
        with patch.object(remove.runtime, 'ensure_game_stopped', side_effect=RuntimeError('running')), \
                self.assertRaisesRegex(RuntimeError, 'running'):
            self.run_remove()
        self.assertTrue(self.pack.exists())
