"""One-shot main-menu connection using the game's own connection and favorites APIs."""
import os
from pathlib import Path
import sys
import tempfile
import time

SCRIPT_REL = Path('media/lua/client/PZLauncherConnect.lua')
REQUEST_NAME = 'pz-launcher-request.txt'


def validate(host, port, username, password, server_password):
    values = [host.strip(), port.strip(), username.strip(), password, server_password]
    if any(any(ord(c) < 32 or ord(c) == 127 for c in v) for v in values):
        raise ValueError('계정 정보에는 줄바꿈이나 제어 문자를 넣을 수 없습니다.')
    if not values[0] or any(c in values[0] for c in '/\\ :'):
        raise ValueError('서버 주소를 확인해주세요.')
    if not values[1].isascii() or not values[1].isdigit() or not 1 <= int(values[1]) <= 65535:
        raise ValueError('서버 포트는 1~65535로 입력해주세요.')
    if not values[2] or len(values[2]) > 64:
        raise ValueError('게임 계정명을 입력해주세요 (최대 64자).')
    if not password:
        raise ValueError('게임 계정 비밀번호를 입력해주세요.')
    return tuple(values)


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def prepare(game_dir, lua_dir, credentials):
    values = validate(*credentials)
    game, cache = Path(game_dir), Path(lua_dir)
    script = game / SCRIPT_REL
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'launcher_connect.lua'
    content = source.read_bytes()
    if script.exists() and not script.read_bytes().startswith(b'-- Installed only by the launcher.'):
        raise RuntimeError('자동 접속 스크립트 경로에 다른 파일이 있습니다. 파일을 확인해주세요.')
    request = cache / REQUEST_NAME
    try:
        _atomic(script, content)
        _atomic(request, ('\n'.join([str(int((time.time() + 600) * 1000)), *values]) + '\n').encode('utf-8'))
    except Exception:
        cleanup(game, cache)
        raise


def cleanup(game_dir, lua_dir):
    (Path(lua_dir) / REQUEST_NAME).unlink(missing_ok=True)
    script = Path(game_dir) / SCRIPT_REL
    if script.is_file() and script.read_bytes().startswith(b'-- Installed only by the launcher.'):
        script.unlink()
