"""Transactional removal of explicitly owned mod folders; never touches saves."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import game_runtime as runtime
from modpack_format import folder_name


def _folder_name(value):
    return folder_name(value)


def _mod_ids(folder):
    ids = set()
    for info in folder.rglob('mod.info'):
        # Do not follow a mod's symlinks into unrelated files.
        if info.is_symlink() or not info.resolve().is_relative_to(folder.resolve()):
            continue
        for line in info.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            match = re.match(r'^\s*id\s*=\s*(.*?)\s*$', line)
            if match and match[1]:
                ids.add(match[1])
    return ids


def _filter_modlist(raw, removed_ids):
    # Byte-level filtering preserves BOM, VERSION, comments, whitespace and CRLF.
    result = []
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b'\r\n')
        end = line[len(body):]
        probe = body.decode('utf-8-sig', errors='replace').strip()
        if not probe or probe.startswith(('VERSION=', '#', '--')):
            result.append(line)
            continue
        parts = body.split(b';')
        keep = [p for p in parts if p.decode('utf-8-sig', errors='replace').strip() not in removed_ids]
        result.append(b';'.join(keep) + end)
    return b''.join(result)


def _filter_loaded(raw, removed_ids):
    return b''.join(line for line in raw.splitlines(keepends=True)
                    if line.decode('utf-8', errors='replace').strip() not in removed_ids)


def _filter_default(raw, removed_ids):
    # ActiveModsFile/ScriptParser use comma-terminated `mod = ID,` values,
    # not quoted string literals. ActiveModsFile strips backslashes from IDs.
    # Mask comments only for matching; preserve original bytes everywhere else.
    masked = re.sub(rb'/\*.*?\*/', lambda m: b' ' * len(m[0]), raw, flags=re.S)
    spans = []
    for block in re.finditer(rb'\bmods\s*\{([^{}]*)\}', masked):
        body = block[1]
        start = block.start(1)
        offset = 0
        for field in body.split(b',')[:-1]:
            match = re.match(rb'\s*(mod)\s*=\s*(.*?)\s*$', field, re.I | re.S)
            if match:
                mod_id = match[2].decode('utf-8', errors='replace').strip().replace('\\', '')
                if mod_id in removed_ids:
                    spans.append((start + offset + match.start(1), start + offset + len(field) + 1))
            offset += len(field) + 1
    for start, end in reversed(spans):
        raw = raw[:start] + raw[end:]
    return raw


def remove_modpack(game_dir, mods_dir, lua_dir, state_file, folders, managed_file=None):
    if not isinstance(folders, (list, tuple, set)):
        raise ValueError('제거할 모드 목록이 올바르지 않습니다.')
    names = list(dict.fromkeys(_folder_name(name) for name in folders))
    game, mods, lua, state = map(Path, (game_dir, mods_dir, lua_dir, state_file))
    runtime.ensure_game_stopped(game)
    if mods.is_symlink():
        raise ValueError('링크된 모드 폴더는 자동 제거할 수 없습니다.')
    selected = []
    ids = set()
    for name in names:
        folder = mods / name
        if folder.is_symlink():
            raise ValueError('링크된 모드는 자동 제거할 수 없습니다: ' + name)
        if folder.exists():
            if not folder.is_dir():
                raise ValueError('모드 경로가 폴더가 아닙니다: ' + name)
            selected.append(folder)
            ids.update(_mod_ids(folder))
    # A private mod can share an ID with an owned folder. Keep its activation.
    if mods.exists():
        for folder in mods.iterdir():
            if folder.is_dir() and not folder.is_symlink() and folder not in selected:
                ids.difference_update(_mod_ids(folder))
    modlist = lua / 'modmanager-mods.txt'
    managed = Path(managed_file) if managed_file else state.parent / '_modpack_managed.json'
    default, loaded = mods / 'default.txt', mods / 'loaded.txt'
    tracked = list(dict.fromkeys([state, managed, modlist, default, loaded]))
    if any(path.is_symlink() for path in tracked):
        raise ValueError('링크된 설정 파일은 자동 제거할 수 없습니다.')
    originals = {path: path.read_bytes() if path.exists() else None for path in tracked}
    backup = Path(tempfile.mkdtemp(prefix='.pz-remove-backup-', dir=mods.parent))
    moved = []
    preserve = False
    try:
        (backup / 'mods').mkdir()
        records = []
        for i, (path, data) in enumerate(originals.items()):
            if data is not None:
                (backup / str(i)).write_bytes(data)
            records.append({'path': str(path.absolute()), 'backup': str(i) if data is not None else None})
        (backup / 'restore.json').write_text(json.dumps({
            'files': records, 'mods_dir': str(mods.absolute()),
            'folders': [path.name for path in selected]}, ensure_ascii=False, indent=2), encoding='utf-8')
        for folder in selected:
            os.replace(folder, backup / 'mods' / folder.name)
            moved.append(folder)
        if originals[modlist] is not None:
            runtime._atomic_write(modlist, _filter_modlist(originals[modlist], ids))
        for path, filter_ids in ((default, _filter_default), (loaded, _filter_loaded)):
            if originals[path] is not None:
                runtime._atomic_write(path, filter_ids(originals[path], ids))
        state.unlink(missing_ok=True)
        managed.unlink(missing_ok=True)
    except Exception as error:
        failures = []
        for folder in reversed(moved):
            try:
                os.replace(backup / 'mods' / folder.name, folder)
            except Exception as exc:
                failures.append(exc)
        for path, data in originals.items():
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                elif not path.exists() or path.read_bytes() != data:
                    runtime._atomic_write(path, data)
            except Exception as exc:
                failures.append(exc)
        if failures:
            preserve = True
            raise RuntimeError(f'모드 제거 복구를 완료하지 못했습니다. 복구 백업: {backup}') from error
        raise
    finally:
        if not preserve:
            shutil.rmtree(backup, ignore_errors=True)
    return {'removed': [path.name for path in selected],
            'keptcount': sum(path.is_dir() for path in mods.iterdir()) if mods.exists() else 0}
