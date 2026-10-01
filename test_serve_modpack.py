import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import serve_modpack
import test_installer_versions as fixtures


class ServingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.sources = self.base / 'mods'
        (self.sources / 'A/42').mkdir(parents=True)
        (self.sources / 'A/42/mod.info').write_text('id=Example\n')
        self.file = self.sources / 'A/42/content.txt'
        self.file.write_text('one')
        self.publisher = serve_modpack.Publisher(self.sources, self.base / 'published')
        self.publisher.publish()

    def start_server(self):
        self.server = serve_modpack.create_server(self.publisher, port=0)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}/dist'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        with self.opener.open(self.url + path) as response:
            return response.read()

    def test_changes_publish_automatically_after_two_stable_scans(self):
        self.file.write_text('two with more content')
        self.assertFalse(self.publisher.poll_once())
        self.assertTrue(self.publisher.poll_once())
        self.assertEqual(self.publisher.version, 2)
        manifest = json.loads((self.publisher.current / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['archive_base'], 'releases/v2')

    def test_unchanged_restart_keeps_the_current_version(self):
        restarted = serve_modpack.Publisher(self.sources, self.base / 'published')
        self.assertFalse(restarted.publish())
        self.assertEqual(restarted.version, 1)

    def test_old_snapshot_stays_available_after_new_publish(self):
        self.start_server()
        old = self.get('/releases/v1/mods.zip')
        self.file.write_text('updated')
        self.publisher.publish()
        self.assertEqual(self.get('/releases/v1/mods.zip'), old)
        self.assertNotEqual(self.get('/mods.zip'), old)
        self.assertEqual(json.loads(self.get('/manifest.json'))['latest_version'], 2)

    def test_short_connections_receive_complete_responses(self):
        self.start_server()
        for _ in range(20):
            self.assertEqual(json.loads(self.get('/manifest.json'))['latest_version'], 1)

    def test_file_allowlist_hides_state_private_files_and_parent_directories(self):
        self.start_server()
        (self.publisher.current / 'secret.txt').write_text('not public')
        for path in ['/current.json', '/secret.txt', '/../current.json', '/releases/v1/secret.txt', '/mods/../manifest.json']:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as raised:
                self.get(path)
            self.assertEqual(raised.exception.code, 404)

    def test_server_updates_are_consumed_by_real_launcher_downloads(self):
        self.start_server()
        case = fixtures.VersionTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        app = case.app
        app.settings['modpack_url'] = self.url
        app._fetch_manifest = fixtures.installer.PZModInstaller._fetch_manifest.__get__(app)
        app._regen_modlist = fixtures.installer.PZModInstaller._regen_modlist.__get__(app)
        app._clear_version()
        from unittest.mock import patch
        with patch.object(fixtures.installer.urllib.request, 'urlopen', side_effect=self.opener.open):
            app._run_update()
            self.assertEqual(app._read_version(), 1)
            self.file.write_text('version two')
            self.publisher.poll_once()
            self.publisher.poll_once()
            app._run_update()
        self.assertEqual(app._read_version(), 2)
        self.assertEqual((Path(app.mods_path) / 'A/42/content.txt').read_text(), 'version two')

    def test_builder_error_keeps_the_previous_published_files(self):
        old = self.publisher.current
        (self.sources / 'B').mkdir()
        with self.assertRaises(ValueError):
            self.publisher.publish()
        self.assertEqual(self.publisher.current, old)
        self.assertEqual(json.loads((self.publisher.out / 'current.json').read_text())['version'], 1)

    def test_output_cannot_overlap_mod_sources(self):
        with self.assertRaises(ValueError):
            serve_modpack.Publisher(self.sources, self.sources / 'public')
