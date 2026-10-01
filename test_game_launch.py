import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import game_launch


class GameLaunchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pz-launch-test-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.game = self.base / 'game with spaces'
        (self.game / 'jre64/bin').mkdir(parents=True)
        (self.game / 'jre64/bin/java.exe').touch()
        self.config = {'mainClass': 'zombie/gameStates/MainScreen', 'classpath': ['.', 'game.jar'],
                       'vmArgs': ['-Xmx4g', '-Dcustom=yes'], 'windows': {'vmArgs': ['-Dplatform=windows']}}
        self.write_config()
        self.popen = patch.object(game_launch.subprocess, 'Popen', return_value=Mock())
        self.process = self.popen.start()
        self.addCleanup(self.popen.stop)
        stopped = patch.object(game_launch.runtime, 'ensure_game_stopped')
        stopped.start()
        self.addCleanup(stopped.stop)

    def write_config(self):
        (self.game / 'ProjectZomboid64.json').write_text(json.dumps(self.config), encoding='utf-8')

    def launch(self, **kwargs):
        return game_launch.launch_game(self.game, self.base / 'launch.log', **kwargs)

    def jar(self, name='patches/custom.jar'):
        path = self.game / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Premain-Class: example.Agent\n')
        return path

    def test_plain_client_launch_has_no_patch_dependency_and_preserves_config(self):
        before = (self.game / 'ProjectZomboid64.json').read_bytes()
        with patch.dict(os.environ, {'steamappid': 'bad', 'SteamGameId': 'bad'}):
            self.launch()
        argv = self.process.call_args.args[0]
        self.assertFalse(any(arg.startswith('-javaagent:') for arg in argv))
        self.assertIn('-Dcustom=yes', argv)
        self.assertIn('-Dplatform=windows', argv)
        self.assertEqual(argv[-3:], ['-cp', '.;game.jar', 'zombie.gameStates.MainScreen'])
        self.assertEqual(self.process.call_args.kwargs['env']['SteamAppId'], '108600')
        self.assertEqual((self.game / 'ProjectZomboid64.json').read_bytes(), before)
        self.assertFalse(self.process.call_args.kwargs['shell'])

    def test_selected_agent_and_options_are_a_single_argument_with_spaces(self):
        jar = self.jar('patches/my patch.jar')
        self.launch(java_agent='patches/my patch.jar', java_agent_options='debug=true,name=a b')
        self.assertIn('-javaagent:' + str(jar.resolve()) + '=debug=true,name=a b', self.process.call_args.args[0])

    def test_existing_agent_options_are_preserved_by_default(self):
        self.jar()
        self.config['vmArgs'].append('-javaagent:patches/custom.jar=old')
        self.write_config()
        self.launch()
        self.assertIn('-javaagent:patches/custom.jar=old', self.process.call_args.args[0])

    def test_selected_agent_replaces_its_existing_options_without_duplicate_loading(self):
        self.jar()
        self.config['vmArgs'] += ['-javaagent:patches/custom.jar=old', '-javaagent:other.jar']
        self.write_config()
        self.launch(java_agent='patches/custom.jar', java_agent_options='new')
        agents = [arg for arg in self.process.call_args.args[0] if arg.startswith('-javaagent:')]
        self.assertEqual(len(agents), 2)
        self.assertIn('-javaagent:other.jar', agents)
        self.assertTrue(any(arg.endswith('=new') for arg in agents))

    def test_missing_or_corrupt_patch_never_starts_java(self):
        for name in ['absent.jar', 'bad.jar']:
            if name == 'bad.jar':
                (self.game / name).write_bytes(b'not a jar')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.launch(java_agent=name)
        self.process.assert_not_called()

    def test_bundled_patch_is_cached_outside_temporary_extraction_directory(self):
        assets = self.base / 'bundle'
        (assets / 'patches').mkdir(parents=True)
        jar = self.jar()
        (assets / 'patches/bundled.jar').write_bytes(jar.read_bytes())
        with patch.object(game_launch.sys, '_MEIPASS', str(assets), create=True), \
                patch.dict(os.environ, {'USERPROFILE': str(self.base / 'user')}):
            self.launch(java_agent='patches/bundled.jar')
        arg = next(arg for arg in self.process.call_args.args[0] if arg.startswith('-javaagent:'))
        cached = Path(arg[len('-javaagent:'):])
        self.assertTrue(cached.is_relative_to(self.base / 'user'))
        self.assertEqual(cached.read_bytes(), jar.read_bytes())

    def test_windows_profile_uses_newest_applicable_vm_args(self):
        self.config['windows'].update({'6.1': {'vmArgs': ['-Dlegacy=yes']},
                                       '10.0.17134': {'vmArgs': ['-Dmodern=yes']}})
        self.write_config()
        with patch.object(game_launch, '_windows_version', return_value=(10, 0, 22631)):
            self.launch()
        self.assertIn('-Dmodern=yes', self.process.call_args.args[0])
        self.assertNotIn('-Dlegacy=yes', self.process.call_args.args[0])

    def test_server_directory_cannot_start_as_a_client(self):
        self.config['mainClass'] = 'zombie.network.GameServer'
        self.write_config()
        with self.assertRaises(ValueError):
            self.launch()
        self.process.assert_not_called()
