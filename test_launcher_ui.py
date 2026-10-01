"""Launch workflow tests never start Steam, Java or the real game."""
import unittest
import json
from unittest.mock import Mock, patch
import test_installer_versions as fixtures

app_module = fixtures.installer


class LaunchWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixtures.VersionTests.setUp(self)
        self.app.pz_install_path = str(self.base / 'game')
        self.app._run_update = Mock()
        self.app.game_process = None
        self.process = Mock(returncode=0)
        self.process.poll.return_value = None
        self.launch = patch.object(app_module.game_launch, 'launch_game', return_value=self.process)
        self.launch_mock = self.launch.start()
        self.addCleanup(self.launch.stop)

    def test_updates_before_direct_launch_and_keeps_process_for_locking(self):
        order = []
        self.app._run_update.side_effect = lambda **kw: order.append(('update', self.app._launching, kw))
        self.launch_mock.side_effect = lambda *args, **kw: order.append(('launch',)) or self.process
        with patch.object(app_module.time, 'monotonic', side_effect=[0, 4]), \
             patch.object(app_module.threading, 'Thread') as thread:
            self.app._run_launch()
        self.assertEqual(order, [('update', True, {'prepared': True}), ('launch',)])
        self.assertIs(self.app.game_process, self.process)
        self.assertFalse(self.app._launching)
        self.assertEqual(self.launch_mock.call_args.args[1], self.base / 'pz-launcher.log')
        thread.return_value.start.assert_called_once()

    def test_connection_is_prepared_after_update_and_before_java(self):
        credentials = ('example.invalid', '16261', 'player', 'secret', '')
        order = []
        self.app._run_update.side_effect = lambda **kw: order.append('update')
        self.launch_mock.side_effect = lambda *args, **kw: order.append('java') or self.process
        with patch.object(app_module.server_connect, 'prepare', side_effect=lambda *a: order.append('connect')) as prepare, \
             patch.object(app_module.time, 'monotonic', side_effect=[0, 4]), \
             patch.object(app_module.threading, 'Thread'):
            self.app._run_launch(credentials)
        self.assertEqual(order, ['update', 'connect', 'java'])
        self.assertEqual(prepare.call_args.args[-1], credentials)

    def test_failed_java_start_cleans_up_credentials(self):
        self.launch_mock.side_effect = OSError('JVM failed')
        with patch.object(app_module.server_connect, 'prepare'), \
             patch.object(app_module.server_connect, 'cleanup') as cleanup, \
             self.assertRaises(OSError):
            self.app._run_launch(('example.invalid', '16261', 'player', 'secret', ''))
        cleanup.assert_called_once_with(self.app.pz_install_path, self.app.lua_dir)

    def test_update_failure_never_launches_game(self):
        self.app._run_update.side_effect = OSError('download failed')
        with self.assertRaises(OSError):
            self.app._run_launch()
        self.launch_mock.assert_not_called()
        self.assertFalse(self.app._launching)

    def test_early_jvm_exit_reports_log_path(self):
        self.process.poll.return_value = 78
        self.process.returncode = 78
        with self.assertRaisesRegex(RuntimeError, '78.*pz-launcher.log'):
            self.app._run_launch()
        self.assertIsNone(self.app.game_process)
        self.assertFalse(self.app._launching)

    def test_install_buttons_stay_disabled_until_game_exits(self):
        self.app.game_process = self.process
        self.app.action_btns = [Mock(), Mock()]
        self.app._set_buttons(True)
        for button in self.app.action_btns:
            button.config.assert_called_with(state='disabled')
        self.process.poll.return_value = 0
        self.app._set_buttons(True)
        for button in self.app.action_btns:
            button.config.assert_called_with(state='normal')

    def test_remove_cancel_does_not_modify_install(self):
        self.app._step_check_steam = Mock()
        self.app._step_check_pz = Mock()
        self.app._managed_path().write_text(json.dumps({'folders': ['A']}))
        self.app._ask_on_main = Mock(return_value=False)
        with patch.object(app_module.modpack_remove, 'remove_modpack') as remove:
            self.app._run_remove()
        remove.assert_not_called()
        self.assertTrue((self.base / 'mods/A/old.txt').is_file())

    def test_remove_uses_recorded_ownership(self):
        self.app._step_check_steam = Mock()
        self.app._step_check_pz = Mock()
        self.app._managed_path().write_text(json.dumps({'folders': ['A']}))
        self.app._ask_on_main = Mock(return_value=True)
        with patch.object(app_module.modpack_remove, 'remove_modpack',
                          return_value={'removed': ['A'], 'keptcount': 0}) as remove:
            self.app._run_remove()
        self.assertEqual(remove.call_args.args[-1], ['A'])

    def test_ownership_tracks_manifest_pack_not_personal_folders(self):
        self.app._remember_managed({'digests': {'A': 'hash'}}, folders=['A', 'Personal'])
        self.assertEqual(json.loads(self.app._managed_path().read_text(encoding='utf-8'))['folders'], ['A'])

    def test_general_game_launch_never_requires_modpack_server(self):
        self.app.settings['modpack_url'] = ''
        with patch.object(app_module.time, 'monotonic', side_effect=[0, 4]), \
                patch.object(app_module.threading, 'Thread'):
            self.app._run_launch()
        self.app._run_update.assert_not_called()
        self.assertEqual(self.launch_mock.call_args.kwargs, {'java_agent': '', 'java_agent_options': ''})

    def test_selected_agent_and_options_reach_launch_without_installing_patch(self):
        self.app.settings.update(java_agent='patches/custom.jar', java_agent_options='debug=true')
        with patch.object(app_module.time, 'monotonic', side_effect=[0, 4]), \
                patch.object(app_module.threading, 'Thread'):
            self.app._run_launch()
        self.assertEqual(self.launch_mock.call_args.kwargs,
                         {'java_agent': 'patches/custom.jar', 'java_agent_options': 'debug=true'})

    def test_launcher_messages_hide_game_host_and_modpack_url(self):
        self.app.settings.update(server_host='play.example.invalid', modpack_url='https://files.example.invalid/dist')
        text = self.app._display_text('Cannot connect to play.example.invalid:16261 or https://files.example.invalid/dist/mods/A.zip')
        self.assertNotIn('play.example.invalid', text)
        self.assertNotIn('files.example.invalid', text)
        self.assertIn('/mods/A.zip', text)

    def test_host_redaction_is_case_insensitive_and_keeps_unrelated_messages(self):
        self.app.settings['server_host'] = 'play.example.invalid'
        self.assertNotIn('PLAY.EXAMPLE.INVALID', self.app._display_text('Host PLAY.EXAMPLE.INVALID failed'))
        self.assertEqual(self.app._display_text('모드 3개 업데이트 완료'), '모드 3개 업데이트 완료')

    def test_login_uses_two_account_fields_and_the_built_in_server_password(self):
        self.app.settings.update(server_host='example.invalid', server_password='build-only secret')
        self.app.connection_entries = [Mock(), Mock()]
        self.app.connection_entries[0].get.return_value = 'player'
        self.app.connection_entries[1].get.return_value = 'account secret'
        self.app._run_launch = Mock()
        self.app._start = lambda action: action()
        self.app._on_launch()
        self.app._run_launch.assert_called_once_with(
            ('example.invalid', '16261', 'player', 'account secret', 'build-only secret'))


if __name__ == '__main__':
    unittest.main()
