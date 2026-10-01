"""Start the Windows client with its bundled JVM, bypassing the native launcher."""

import os
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import game_runtime as runtime


def _strings(value, label):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"게임 런처의 {label} 형식이 올바르지 않습니다.")
    return value


def _windows_version():
    if not hasattr(sys, "getwindowsversion"):
        raise RuntimeError("Windows 버전별 게임 옵션은 Windows에서 확인해야 합니다.")
    version = sys.getwindowsversion()
    return tuple(getattr(version, "platform_version", (version.major, version.minor, version.build)))


def _windows_vm_args(config):
    windows = config.get("windows", {})
    if not isinstance(windows, dict):
        raise ValueError("게임 런처의 windows 설정이 올바르지 않습니다.")
    extra = list(_strings(windows.get("vmArgs", []), "windows.vmArgs"))
    # Shipped configs have Windows-version profiles (e.g. 6.1 and 10.0.17134).
    # Select the newest applicable profile rather than combining conflicting GCs.
    profiles = [(tuple(map(int, key.split("."))), value) for key, value in windows.items()
                if re.fullmatch(r"\d+(?:\.\d+){1,3}", key)]
    if profiles:
        current = (*_windows_version(), 0)[:4]
        eligible = [(version + (0,) * (4 - len(version)), value) for version, value in profiles
                    if version + (0,) * (4 - len(version)) <= current]
        if eligible:
            _, profile = max(eligible, key=lambda pair: pair[0])
            if not isinstance(profile, dict):
                raise ValueError("게임 런처의 Windows 버전별 설정이 올바르지 않습니다.")
            extra.extend(_strings(profile.get("vmArgs", []), "windows.<version>.vmArgs"))
    return extra


def _agent_argument(game, agent_path, options=""):
    if not agent_path:
        return None
    if any(ord(c) < 32 for c in agent_path + options) or "=" in agent_path:
        raise ValueError("Java 패치 경로 또는 옵션을 확인해주세요.")
    path = Path(agent_path)
    if not path.is_absolute():
        launcher = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        assets = Path(getattr(sys, "_MEIPASS", launcher))
        candidates = [game / path, launcher / path, assets / path]
        path = next((p for p in candidates if p.is_file()), candidates[0])
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".jar" or not zipfile.is_zipfile(path):
        raise ValueError(f"Java 패치 JAR를 찾을 수 없거나 올바른 JAR가 아닙니다: {path}")
    # A one-file EXE's extraction directory disappears when the launcher closes.
    # Cache its agent so lazy class loading continues while the game is running.
    assets = getattr(sys, "_MEIPASS", None)
    if assets and path.is_relative_to(Path(assets).resolve()):
        data = path.read_bytes()
        profile = Path(os.environ.get("USERPROFILE") or Path.home())
        path = profile / "Zomboid/launchers/runtime" / (hashlib.sha256(data).hexdigest() + ".jar")
        if not path.is_file() or path.read_bytes() != data:
            runtime._atomic_write(path, data)
    return "-javaagent:" + str(path) + ("=" + options if options else "")


def _same_agent(arg, extra, game):
    if not arg.startswith("-javaagent:"):
        return False
    existing = Path(arg[len("-javaagent:"):].split("=", 1)[0])
    selected = Path(extra[len("-javaagent:"):].split("=", 1)[0])
    return (game / existing).resolve() == selected.resolve()


def launch_game(game_dir, log_path=None, *, java_agent="", java_agent_options=""):
    """Return Popen; caller monitors startup and displays the log on early exit."""
    game = Path(game_dir).resolve()
    runtime.ensure_game_stopped(game)
    _, config = runtime._read_config(game)
    if runtime.is_server_config(config):
        raise ValueError("서버 설치 폴더에서는 클라이언트를 실행할 수 없습니다.")
    main = str(config.get("mainClass", "")).replace("/", ".")
    if not re.fullmatch(r"[A-Za-z_$][\w.$]*", main):
        raise ValueError("게임 런처의 mainClass가 올바르지 않습니다.")
    java = game / "jre64/bin/java.exe"
    if not java.is_file():
        raise FileNotFoundError("게임의 jre64/bin/java.exe를 찾을 수 없습니다. Steam에서 게임 파일을 확인하세요.")
    classpath = _strings(config.get("classpath"), "classpath")
    if not classpath:
        raise ValueError("게임 런처의 classpath가 비어 있습니다.")
    combined = _strings(config.get("vmArgs"), "vmArgs") + _windows_vm_args(config)
    selected_agent = _agent_argument(game, java_agent, java_agent_options)
    if selected_agent:
        # Explicit settings replace options for the same agent, leaving others intact.
        combined = [arg for arg in combined if not _same_agent(arg, selected_agent, game)]
        combined.append(selected_agent)
    vm_args = list(dict.fromkeys(combined))
    # These are Windows launcher inputs even when unit tests run on Linux.
    argv = [str(java), *vm_args, "-cp", ";".join(classpath), main]
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in ("steamappid", "steamgameid"):
            del env[key]
    env.update(SteamAppId="108600", SteamGameId="108600")
    env["PATH"] = ";".join([str(game), str(game / "win64"), str(java.parent), env.get("PATH", "")])
    if log_path is None:
        profile = Path(os.environ.get("USERPROFILE") or Path.home())
        log_path = profile / "Zomboid/pz-launcher.log"
    log = Path(log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        output.write(b"\n--- Project Zomboid bundled JVM launch ---\n")
        output.flush()
        return subprocess.Popen(argv, cwd=str(game), env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                shell=False)
