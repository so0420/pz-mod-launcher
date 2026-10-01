import functools
import http.server
import json
from pathlib import Path
import shutil
import threading
import urllib.request
import unittest
from unittest.mock import Mock, patch
import zipfile

import build_modpack
import modpack_format
import test_installer_versions as fixtures


class ModpackTests(unittest.TestCase):
    def setUp(self):
        fixtures.VersionTests.setUp(self)
        self.sources = self.base / 'source'
        self.out = self.base / 'public'
        (self.sources / 'A/42').mkdir(parents=True)
        (self.sources / 'A/42/mod.info').write_text('id=ExampleA\n', encoding='utf-8')
        (self.sources / 'A/42/file.txt').write_text('first')

    def test_builder_tracks_changes_deletions_and_monotonic_versions(self):
        first = build_modpack.build(self.sources, self.out, 1)
        self.assertEqual(first['versions'][-1]['changed'], ['A'])
        second = build_modpack.build(self.sources, self.out, 2)
        self.assertEqual(second['versions'][-1]['changed'], [])
        (self.sources / 'B').mkdir()
        (self.sources / 'B/mod.info').write_text('id=ExampleB\n')
        shutil.rmtree(self.sources / 'A')
        third = build_modpack.build(self.sources, self.out, 3)
        self.assertEqual(third['versions'][-1]['removed'], ['A'])
        self.assertEqual(third['versions'][-1]['changed'], ['B'])
        self.assertFalse((self.out / 'mods/A.zip').exists())
        with self.assertRaises(ValueError):
            build_modpack.build(self.sources, self.out, 3)

    def test_full_install_incremental_update_and_removal_over_http(self):
        build_modpack.build(self.sources, self.out, 1)
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            timeout = 15
            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError:
                    pass
            def do_GET(self):
                super().do_GET()
                self.close_connection = False
            def log_message(self, *args):
                pass
        handler = functools.partial(QuietHandler, directory=str(self.out))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.app.settings['modpack_url'] = f'http://127.0.0.1:{server.server_port}'
        self.app._clear_version()
        personal = self.base / 'mods/Personal'
        personal.mkdir()
        (personal / 'mod.info').write_text('id=Personal\n')
        self.app._fetch_manifest = fixtures.installer.PZModInstaller._fetch_manifest.__get__(self.app)
        self.app._regen_modlist = fixtures.installer.PZModInstaller._regen_modlist.__get__(self.app)
        self.app._set_progress = Mock()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        network = patch.object(fixtures.installer.urllib.request, 'urlopen', side_effect=opener.open)
        network.start()
        self.addCleanup(network.stop)
        self.app._run_update()
        self.assertEqual(self.app._read_version(), 1)
        self.assertTrue((personal / 'mod.info').exists())
        self.assertEqual(self.app._owned_folders(), ['A'])
        (self.sources / 'A/42/file.txt').write_text('second')
        (self.sources / 'B').mkdir()
        (self.sources / 'B/mod.info').write_text('id=ExampleB\n')
        build_modpack.build(self.sources, self.out, 2)
        self.app._run_update()
        self.assertEqual((self.base / 'mods/A/42/file.txt').read_text(), 'second')
        self.assertEqual(self.app._read_version(), 2)
        shutil.rmtree(self.sources / 'A')
        build_modpack.build(self.sources, self.out, 3)
        self.app._run_update()
        self.assertFalse((self.base / 'mods/A').exists())
        self.assertTrue((personal / 'mod.info').exists())
        self.assertEqual(self.app._owned_folders(), ['B'])

    def test_full_install_preserves_personal_mods_and_records_only_pack_folders(self):
        personal = self.base / 'mods/Personal'
        personal.mkdir()
        (personal / 'mod.info').write_text('id=Personal\n')
        archive = self.archive('full.zip', {'B/mod.info': 'id=B'})
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        self.app._full_install(None)
        self.assertTrue((personal / 'mod.info').exists())
        self.assertFalse((self.base / 'mods/A').exists())
        self.assertEqual(self.app._owned_folders(), ['B'])

    archive = fixtures.VersionTests.archive

    def test_personal_folder_collision_never_overwrites_existing_mod(self):
        archive = self.archive('full.zip', {'Personal/mod.info': 'id=Pack'})
        personal = self.base / 'mods/Personal'
        personal.mkdir()
        (personal / 'mod.info').write_text('id=Personal\n')
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        with self.assertRaisesRegex(ValueError, '개인 모드'):
            self.app._full_install(None)
        self.assertEqual((personal / 'mod.info').read_text(), 'id=Personal\n')
        self.assertEqual(self.app._read_version(), 1)

    def test_zip_path_traversal_and_windows_aliases_are_rejected(self):
        for member in ['../outside.txt', 'A/../../outside', 'C:/outside', 'A\\outside', 'A/NUL', 'A/file.']:
            entry = zipfile.ZipInfo('placeholder')
            entry.filename = member  # Windows ZipInfo constructors normalize backslashes.
            zf = Mock()
            zf.infolist.return_value = [entry]
            with self.subTest(member=member), self.assertRaises(ValueError):
                modpack_format.archive_members(zf)

    def test_incremental_archive_cannot_replace_an_unrelated_mod(self):
        archive = self.archive('wrong.zip', {'Personal/mod.info': 'id=Bad'})
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        with self.assertRaises(ValueError):
            self.app._run_update()
        self.assertEqual((self.base / 'mods/A/old.txt').read_text(), 'old')
        self.assertEqual(self.app._read_version(), 1)

    def test_hash_failure_preserves_existing_install(self):
        archive = self.archive('bad-hash.zip', {'A/mod.info': 'id=A'})
        self.manifest['archives'] = {'mods/A.zip': '0' * 64}
        self.app._download = lambda url, dest, label: shutil.copyfile(archive, dest)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.app._run_update()
        self.assertEqual((self.base / 'mods/A/old.txt').read_text(), 'old')

    def test_source_url_change_invalidates_the_previous_server_version(self):
        self.app.settings['modpack_url'] = 'https://other.invalid/modpack'
        self.assertIsNone(self.app._read_version())

    def test_unsafe_manifest_folder_cannot_delete_outside_mods(self):
        with self.assertRaises(ValueError):
            modpack_format.validate_manifest({'latest_version': 2, 'versions': [
                {'version': 2, 'removed': ['../outside']} ]})
