import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import launcher_config as config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.path = self.base / 'launcher-config.json'

    def test_missing_config_defaults_to_general_game_without_server_or_patch(self):
        self.assertEqual(config.load(self.path, environ={}), config.DEFAULTS)

    def test_saved_settings_never_persist_passwords_or_unknown_fields(self):
        config.save({'title': '공용 런처', 'password': 'do not store', 'server_password': 'secret'}, self.path)
        text = self.path.read_text(encoding='utf-8')
        self.assertNotIn('secret', text)
        self.assertNotIn('do not store', text)
        self.assertEqual(config.load(self.path, environ={})['title'], '공용 런처')

    def test_external_settings_override_bundled_defaults(self):
        (self.base / 'bundled-config.json').write_text(json.dumps({'title': 'Bundled', 'java_agent': 'patches/test.jar'}))
        with patch.object(config.sys, '_MEIPASS', str(self.base), create=True):
            self.assertEqual(config.load(self.path, environ={})['title'], 'Bundled')
            config.save(dict(config.DEFAULTS, title='External'), self.path)
            settings = config.load(self.path, environ={})
        self.assertEqual(settings['title'], 'External')
        self.assertEqual(settings['java_agent'], '')

    def test_environment_override_validates_and_normalizes_url(self):
        settings = config.load(self.path, environ={'PZ_MODPACK_URL': 'https://example.invalid/modpack/'})
        self.assertEqual(settings['modpack_url'], 'https://example.invalid/modpack')

    def test_invalid_urls_ports_and_pack_ids_are_rejected(self):
        for field, value in [('modpack_url', 'file:///tmp'), ('modpack_url', 'https://user:secret@example.com'),
                             ('modpack_url', 'https://example.com/?token=secret'), ('server_port', '65536'),
                             ('pack_id', '../other'), ('server_host', 'https://example.com'), ('title', 'a\nb')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                config.validate({field: value})

    def test_agent_options_require_a_path(self):
        with self.assertRaises(ValueError):
            config.validate({'java_agent_options': 'debug=true'})

    def test_workshop_delete_is_off_by_default_and_persists_as_a_boolean(self):
        self.assertIs(config.load(self.path, environ={})['force_workshop_delete'], False)
        config.save({'force_workshop_delete': True}, self.path)
        self.assertIs(json.loads(self.path.read_text(encoding='utf-8'))['force_workshop_delete'], True)
        self.assertIs(config.load(self.path, environ={})['force_workshop_delete'], True)

    def test_workshop_delete_rejects_ambiguous_values(self):
        for value in ['true', 'false', '', 1, 0, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate({'force_workshop_delete': value})

    def test_failed_validation_keeps_existing_settings(self):
        config.save({}, self.path)
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            config.save({'server_port': 'bad'}, self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_editing_and_reloading_settings_preserves_embedded_server_password(self):
        bundled = dict(config.DEFAULTS, server_host='example.invalid', server_password='  build-only secret  ')
        (self.base / 'bundled-config.json').write_text(json.dumps(bundled), encoding='utf-8')
        with patch.object(config.sys, '_MEIPASS', str(self.base), create=True):
            settings = config.load(self.path, environ={})
            settings['title'] = 'Edited'
            saved = config.save(settings, self.path)
            self.assertEqual(saved['server_password'], bundled['server_password'])
            self.assertNotIn('server_password', json.loads(self.path.read_text(encoding='utf-8')))
            reloaded = config.load(self.path, environ={})
        self.assertEqual(reloaded['title'], 'Edited')
        self.assertEqual(reloaded['server_password'], bundled['server_password'])

    def test_private_build_settings_load_password_without_trimming_spaces(self):
        private = self.base / 'launcher-build.json'
        private.write_text(json.dumps({'server_host': 'example.invalid', 'server_password': ' pass '}))
        self.assertEqual(config.load(private, environ={})['server_password'], ' pass ')
