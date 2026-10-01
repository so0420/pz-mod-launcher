"""Game process checks and atomic file utilities; no server-specific patches."""
import csv
import io
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import tempfile

CONFIG_NAME = "ProjectZomboid64.json"


def ensure_game_stopped(game_dir=None):
    if os.name != "nt":
        return
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, errors="replace", timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("게임 실행 상태를 확인할 수 없습니다. 게임을 종료하고 다시 시도하세요.")
    java_present = False
    for row in csv.reader(io.StringIO(result.stdout)):
        if row and row[0].lower() in ("projectzomboid64.exe", "projectzomboid32.exe", "projectzomboid.exe"):
            raise RuntimeError("Project Zomboid를 종료한 뒤 설치를 다시 실행하세요.")
        if row and row[0].lower() in ("java.exe", "javaw.exe"):
            java_present = True
    if not java_present:
        return
    # Read process metadata only. No user paths or command text are interpolated
    # into PowerShell, and unrelated Java applications must remain usable.
    query = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
             "@(Get-CimInstance Win32_Process -Filter \"Name='java.exe' OR Name='javaw.exe'\" "
             "| Select-Object Name,ExecutablePath,CommandLine) | ConvertTo-Json -Compress")
    processes = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if processes.returncode:
        raise RuntimeError("Java 게임 실행 상태를 확인할 수 없습니다. 게임을 종료하고 다시 시도하세요.")
    try:
        rows = json.loads(processes.stdout.lstrip("\ufeff") or "[]")
    except ValueError as exc:
        raise RuntimeError("Java 게임 실행 상태 응답을 읽을 수 없습니다.") from exc
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise RuntimeError("Java 게임 실행 상태 응답이 올바르지 않습니다.")
    for row in rows:
        command = str(row.get("CommandLine") or "")
        executable = ntpath.normcase(ntpath.normpath(str(row.get("ExecutablePath") or "")))
        is_main = re.search(r"(?:^|[\s\"])(?:zombie[/.]gameStates[/.]MainScreen(?:State)?|zombie[/.]network[/.]GameServer)(?=[\s\"]|$)", command)
        if game_dir is not None:
            base = ntpath.normcase(ntpath.normpath(str(game_dir)))
            is_game_path = executable in (
                ntpath.join(base, "jre64", "bin", "java.exe"),
                ntpath.join(base, "jre64", "bin", "javaw.exe"))
        else:
            is_game_path = executable.endswith(("\\jre64\\bin\\java.exe", "\\jre64\\bin\\javaw.exe"))
        if is_main and is_game_path:
            raise RuntimeError("Project Zomboid를 종료한 뒤 설치를 다시 실행하세요.")


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_config(game_dir):
    raw = (Path(game_dir) / CONFIG_NAME).read_bytes()
    cfg = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(cfg, dict) or not isinstance(cfg.get("vmArgs"), list) or not all(
            isinstance(arg, str) for arg in cfg["vmArgs"]):
        raise ValueError("ProjectZomboid64.json의 vmArgs 형식이 올바르지 않습니다.")
    return raw, cfg


def is_server_config(cfg):
    return str(cfg.get("mainClass", "")).replace("/", ".") == "zombie.network.GameServer"
