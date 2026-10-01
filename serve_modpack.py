"""Watch a server's mod folders, publish snapshots, and serve only modpack files."""
import argparse
import http.server
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from urllib.parse import unquote, urlsplit

import build_modpack
from game_runtime import _atomic_write
from modpack_format import folder_name, validate_manifest

LOG = logging.getLogger("modpack-server")


class Publisher:
    def __init__(self, mods_dir, out):
        self.mods_dir = Path(mods_dir).resolve()
        self.out = Path(out).resolve()
        if self.out == self.mods_dir or self.out.is_relative_to(self.mods_dir) or self.mods_dir.is_relative_to(self.out):
            raise ValueError("배포 폴더와 모드 원본 폴더는 서로 분리해주세요.")
        self.releases = self.out / "releases"
        self.releases.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.current = None
        self.version = 0
        self.fingerprint = None
        self.pending = None
        state = self.out / "current.json"
        if state.is_file():
            version = json.loads(state.read_text(encoding="utf-8"))["version"]
            if type(version) is not int or version < 1:
                raise ValueError("서버 배포 기록이 올바르지 않습니다.")
            current = self.releases / ("v" + str(version))
            manifest = validate_manifest(json.loads((current / "manifest.json").read_text(encoding="utf-8")))
            self.version, self.current = version, current
            self.previous_digests = manifest.get("digests", {})
        else:
            self.previous_digests = None

    def scan(self):
        if not self.mods_dir.is_dir() or self.mods_dir.is_symlink():
            raise ValueError("모드 원본 폴더를 확인해주세요.")
        entries = []
        for root in sorted(self.mods_dir.iterdir()):
            if not root.is_dir() or root.name.startswith("."):
                continue
            folder_name(root.name)
            if root.is_symlink():
                raise ValueError("링크된 모드는 자동 배포할 수 없습니다.")
            entries.append((root.name, 0, root.stat().st_mtime_ns))
            for path in build_modpack._files(root):
                info = path.stat()
                entries.append((path.relative_to(self.mods_dir).as_posix(), info.st_size, info.st_mtime_ns))
        if not entries:
            raise ValueError("배포할 모드 폴더가 없습니다.")
        return tuple(entries)

    def publish(self, force=False):
        fingerprint = self.scan()
        if fingerprint == self.fingerprint and not force:
            return False
        # Compare contents on restart so an unchanged server keeps its version.
        digests = {p.name: build_modpack.folder_digest(p) for p in sorted(self.mods_dir.iterdir())
                   if p.is_dir() and not p.name.startswith(".")}
        if not force and digests == self.previous_digests:
            self.fingerprint = fingerprint
            return False
        existing = [int(p.name[1:]) for p in self.releases.iterdir()
                    if p.is_dir() and re.fullmatch(r"v[1-9][0-9]*", p.name)]
        version = max([self.version, *existing]) + 1
        target = self.releases / ("v" + str(version))
        if target.exists():
            raise ValueError(f"배포 대상 폴더가 이미 있습니다: {target}")
        with tempfile.TemporaryDirectory(prefix=".build-", dir=self.releases) as temp:
            stage = Path(temp)
            if self.current:
                shutil.copy2(self.current / "manifest.json", stage / "manifest.json")
            manifest = build_modpack.build(self.mods_dir, stage, version, "자동 배포")
            if self.scan() != fingerprint:
                LOG.info("모드 파일이 빌드 중 변경됐습니다. 다음 감지 주기에 다시 빌드합니다.")
                return False
            manifest["archive_base"] = "releases/v" + str(version)
            (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(stage, target)
            _atomic_write(self.out / "current.json", json.dumps({"version": version}).encode("utf-8"))
            with self.lock:
                self.current, self.version = target, version
                self.previous_digests = manifest["digests"]
                self.fingerprint = fingerprint
        LOG.info("v%s 배포 완료 · 모드 %s개", version, len(manifest["digests"]))
        return True

    def poll_once(self):
        fingerprint = self.scan()
        if fingerprint == self.fingerprint:
            self.pending = None
            return False
        # Require two identical scans to avoid packaging files halfway through a copy.
        if fingerprint != self.pending:
            self.pending = fingerprint
            return False
        result = self.publish()
        if result:
            self.pending = None
        return result

    def watch(self, stop, interval):
        while not stop.wait(interval):
            try:
                self.poll_once()
            except Exception:
                LOG.exception("모드 자동 배포 실패 · 기존 배포를 유지합니다")


class ModpackHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 15

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass  # Clients may close immediately after reading a complete response.

    def do_GET(self):
        self._serve(False)
        self.close_connection = False

    def do_HEAD(self):
        self._serve(True)
        self.close_connection = False

    def _serve(self, head_only):
        path = unquote(urlsplit(self.path).path)
        prefix = self.server.url_prefix
        if not path.startswith(prefix + "/"):
            self.send_error(404)
            return
        route = path[len(prefix) + 1:]
        parts = route.split("/")
        publisher = self.server.publisher
        with publisher.lock:
            current = publisher.current
        if len(parts) >= 3 and parts[0] == "releases" and re.fullmatch(r"v[1-9][0-9]*", parts[1]):
            root = publisher.releases / parts[1]
            parts = parts[2:]
        else:
            root = current
        allowed = (parts in (["manifest.json"], ["mods.zip"])) or (
            len(parts) == 2 and parts[0] == "mods" and parts[1].endswith(".zip"))
        try:
            if not allowed or root is None:
                raise ValueError("not a distribution file")
            for part in parts:
                folder_name(part)
            file = root.joinpath(*parts)
            if not file.resolve().is_relative_to(root.resolve()) or file.is_symlink():
                raise ValueError("invalid file path")
            stream = file.open("rb")
        except (ValueError, OSError):
            self.send_error(404)
            return
        with stream:
            size = os.fstat(stream.fileno()).st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8" if file.suffix == ".json" else "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store" if file.name == "manifest.json" else "public, max-age=31536000, immutable" if route.startswith("releases/") else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            # Let the peer close after consuming the response. Closing first on
            # Windows can reset a fast loopback connection before data is read.
            self.send_header("Connection", "close")
            self.end_headers()
            if not head_only:
                try:
                    shutil.copyfileobj(stream, self.wfile, length=1 << 20)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def log_message(self, fmt, *args):
        LOG.info(fmt, *args)


def create_server(publisher, host="127.0.0.1", port=8080, url_prefix="/dist"):
    url_prefix = url_prefix.rstrip("/")
    if url_prefix and (not url_prefix.startswith("/") or any(p in ("", ".", "..") for p in url_prefix[1:].split("/"))):
        raise ValueError("URL prefix를 확인해주세요.")
    server = http.server.ThreadingHTTPServer((host, port), ModpackHandler)
    server.publisher = publisher
    server.url_prefix = url_prefix
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mods-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("dist/server"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--url-prefix", default="/dist")
    parser.add_argument("--poll-interval", type=float, default=5)
    args = parser.parse_args()
    if args.poll_interval <= 0 or not 1 <= args.port <= 65535:
        parser.error("포트와 감지 주기를 확인해주세요.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = Publisher(args.mods_dir, args.out)
    publisher.publish()
    server = create_server(publisher, args.host, args.port, args.url_prefix)
    stop = threading.Event()
    watcher = threading.Thread(target=publisher.watch, args=(stop, args.poll_interval), daemon=True)
    watcher.start()
    LOG.info("서빙 시작: http://%s:%s%s · Ctrl+C로 종료", args.host, args.port, server.url_prefix)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        watcher.join()


if __name__ == "__main__":
    main()
