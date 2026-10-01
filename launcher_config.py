"""Portable settings with a build-time server password that the UI never saves."""
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from game_runtime import _atomic_write

DEFAULTS = {
    "title": "PZ Mod Launcher",
    "pack_id": "default",
    "modpack_url": "",
    "server_host": "",
    "server_port": "16261",
    "server_password": "",
    "force_workshop_delete": False,
    "game_path": "",
    "java_agent": "",
    "java_agent_options": "",
}


def config_path():
    source = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
    return source.resolve().parent / "launcher-config.json"


def validate(values):
    if not isinstance(values, dict):
        raise ValueError("런처 설정은 JSON 객체여야 합니다.")
    settings = dict(DEFAULTS)
    for key in DEFAULTS:
        value = values.get(key, DEFAULTS[key])
        if isinstance(DEFAULTS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key}: true 또는 false를 입력해주세요.")
            settings[key] = value
            continue
        if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"{key}: 한 줄의 문자열을 입력해주세요.")
        settings[key] = value if key == "server_password" else value.strip()
    if not settings["title"] or len(settings["title"]) > 80:
        raise ValueError("런처 이름은 1~80자로 입력해주세요.")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", settings["pack_id"]):
        raise ValueError("모드팩 ID는 영문·숫자·밑줄·하이픈으로 입력해주세요 (최대 48자).")
    # Prefixing the ID when creating directories avoids Windows reserved device names.
    url = settings["modpack_url"].rstrip("/")
    if url:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("모드팩 URL을 확인해주세요.") from exc
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c.isspace() for c in url)):
            raise ValueError("모드팩 URL은 인증정보·쿼리 없는 HTTP(S) 주소로 입력해주세요.")
    settings["modpack_url"] = url
    host = settings["server_host"]
    if host and any(c in host for c in "/\\ :"):
        raise ValueError("서버 주소에는 호스트명 또는 IPv4 주소만 입력해주세요.")
    port = settings["server_port"]
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("서버 포트는 1~65535로 입력해주세요.")
    if "=" in settings["java_agent"]:
        raise ValueError("Java 패치 경로에는 '='를 사용할 수 없습니다. 옵션은 별도 입력해주세요.")
    if settings["java_agent_options"] and not settings["java_agent"]:
        raise ValueError("Java 패치 옵션을 사용하려면 JAR 경로도 지정해주세요.")
    return settings


def load(path=None, environ=None):
    path = Path(path) if path else config_path()
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "bundled-config.json"
    defaults = json.loads(bundled.read_text(encoding="utf-8-sig")) if bundled.exists() else {}
    external = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(defaults, dict) or not isinstance(external, dict):
        raise ValueError("런처 설정은 JSON 객체여야 합니다.")
    values = dict(defaults, **external)
    override = (os.environ if environ is None else environ).get("PZ_MODPACK_URL", "").strip()
    if override:
        values["modpack_url"] = override
    return validate(values)


def save(values, path=None):
    settings = validate(values)
    public = {key: value for key, value in settings.items() if key != "server_password"}
    _atomic_write(path or config_path(),
                  (json.dumps(public, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return settings
