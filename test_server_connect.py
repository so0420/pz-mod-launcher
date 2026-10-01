import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server_connect as connect


class ServerConnectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'game'
        self.cache = Path(self.temp.name) / 'Zomboid/Lua'
        self.creds = ('example.invalid', '16261', '플레이어', 'p " \\ & 비밀', 'server-pass')

    def test_prepare_roundtrips_credentials_as_data_and_cleanup(self):
        with patch.object(connect.time, 'time', return_value=1000):
            connect.prepare(self.game, self.cache, self.creds)
        request = self.cache / connect.REQUEST_NAME
        self.assertEqual(request.read_text(encoding='utf-8').splitlines(), ['1600000', *self.creds])
        script = self.game / connect.SCRIPT_REL
        self.assertNotIn(self.creds[3], script.read_text(encoding='utf-8'))
        connect.cleanup(self.game, self.cache)
        self.assertFalse(request.exists())
        self.assertFalse(script.exists())

    def test_reject_control_injection_and_invalid_port(self):
        for index, value in [(2, 'a\nother'), (3, 'p\rword'), (4, 'p\x00word'), (1, '0'), (1, '65536'), (0, 'a/b')]:
            values = list(self.creds); values[index] = value
            with self.assertRaises(ValueError):
                connect.prepare(self.game, self.cache, values)
        self.assertFalse(self.game.exists())

    def test_never_overwrite_unrelated_game_file(self):
        script = self.game / connect.SCRIPT_REL
        script.parent.mkdir(parents=True); script.write_text('personal file')
        with self.assertRaises(RuntimeError):
            connect.prepare(self.game, self.cache, self.creds)
        connect.cleanup(self.game, self.cache)
        self.assertEqual(script.read_text(), 'personal file')

    def test_failed_request_write_rolls_back_script(self):
        original = connect._atomic
        def write(path, data):
            if path.name == connect.REQUEST_NAME:
                raise OSError('disk full')
            original(path, data)
        with patch.object(connect, '_atomic', side_effect=write), self.assertRaises(OSError):
            connect.prepare(self.game, self.cache, self.creds)
        self.assertFalse((self.game / connect.SCRIPT_REL).exists())

    def test_blank_server_password_is_preserved(self):
        creds = (*self.creds[:4], '')
        connect.prepare(self.game, self.cache, creds)
        self.assertEqual((self.cache / connect.REQUEST_NAME).read_text(encoding='utf-8').splitlines()[-1], '')
