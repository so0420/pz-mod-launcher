"""Reusable Windows launcher and transactional Project Zomboid modpack installer."""

import os
from pathlib import Path
import re
import sys
import json
import time
import shutil
import zipfile
import threading
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import tkinter as tk
from tkinter import messagebox, filedialog
import game_runtime
import launcher_config
import launcher_ui
import modpack_format
import game_launch
import modpack_remove
import server_connect
import workshop_cleanup

# ──────────────────────────────────────────────
PZ_APP_ID = "108600"
WINDOW_TITLE = "PZ Mod Launcher"
WINDOW_SIZE = "740x800"
UA = "PZModLauncher/1.0"


class PZModInstaller:
    def __init__(self):
        self.settings = launcher_config.load()
        self._busy = False
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(700, 740)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.steam_path = None
        self.steam_libraries = []
        self.pz_install_path = None
        self.game_process = None
        self._launching = False
        self.workshop_paths = []

        self._configure_paths()

        self._total_bytes = 0
        self.action_btns = []

        self._build_ui()
        # 시작 시 현재/최신 버전 표시 (백그라운드)
        self._refresh_in_background()

    # ── UI ─────────────────────────────────────

    def _configure_paths(self):
        home = Path.home() / "Zomboid"
        self.mods_path = str(home / "mods")
        self.lua_dir = str(home / "Lua")
        self.state_file = str(home / "launchers" / ("pack-" + self.settings["pack_id"]) / "_modpack_state.json")

    def _build_ui(self):
        launcher_ui.build(self)

    def _refresh_in_background(self):
        threading.Thread(target=self._refresh_versions, daemon=True).start()

    def _url(self, suffix):
        base = self.settings["modpack_url"]
        if not base:
            raise ValueError("설정에서 모드팩 URL을 지정해주세요.")
        return base + "/" + suffix

    def _archive_url(self, manifest, name):
        prefix = manifest.get("archive_base", "") if manifest else ""
        return self._url((prefix + "/" if prefix else "") + name)

    def _close(self):
        if self._busy:
            messagebox.showinfo("작업 진행 중", "설치 또는 실행 준비가 끝난 후 닫아주세요.")
            return
        if self.pz_install_path:
            server_connect.cleanup(self.pz_install_path, self.lua_dir)
        self.root.destroy()

    # ── helpers ────────────────────────────────

    def _display_text(self, value):
        text = str(value)
        url = self.settings.get("modpack_url", "")
        if url:
            text = text.replace(url, "<모드팩 주소>")
        hosts = {self.settings.get("server_host", ""), urllib.parse.urlsplit(url).hostname or ""}
        for host in sorted(hosts, key=len, reverse=True):
            if host:
                text = re.sub(r"(?<![\w.-])" + re.escape(host) + r"(?![\w.-])",
                              "<서버 주소>", text, flags=re.IGNORECASE)
        return text

    def _log(self, msg):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self._log, msg)
            return
        self.log_text.config(state="normal")
        self.log_text.insert("end", self._display_text(msg) + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _set_check(self, key, status):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self._set_check, key, status)
            return
        symbols = {"ok": "✓", "fail": "×", "warn": "!", "wait": "…"}
        colors = {"ok": "#89c9a1", "fail": "#f18d9e", "warn": "#e9c67d", "wait": "#2563eb"}
        self.checks[key].config(text=symbols.get(status, "·"), fg=colors.get(status, "#a59ca8"))

    def _set_progress(self, value, text=""):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self._set_progress, value, text)
            return
        self.progress["value"] = value
        self.progress_label.config(text=text)

    def _ask_on_main(self, dialog_func):
        result = [None]
        event = threading.Event()
        def run():
            result[0] = dialog_func()
            event.set()
        self.root.after(0, run)
        event.wait()
        return result[0]

    def _set_buttons(self, enabled):
        process = getattr(self, "game_process", None)
        if process is not None and process.poll() is None:
            enabled = False
        state = "normal" if enabled else "disabled"
        for b in self.action_btns + getattr(self, "connection_entries", []):
            b.config(state=state)
        if enabled and hasattr(self, "settings_btn"):
            launcher_ui.refresh(self)

    # ── 버전 상태 ──────────────────────────────

    def _read_version(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
                if data.get("source") != self.settings["modpack_url"]:
                    return None
                return int(data.get("version"))
        except Exception:
            return None

    def _write_version(self, v):
        data = {"version": v, "source": self.settings["modpack_url"],
                "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        game_runtime._atomic_write(self.state_file, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _clear_version(self):
        """파일을 변경하기 전에 기존 버전 확정을 취소한다.

        설치가 중단되면 다음 업데이트는 전체 설치로 복구한다. 삭제 실패는
        무시하지 않는다: 이전 버전을 남긴 채 설치 파일만 바꾸면 안 된다.
        """
        try:
            os.remove(self.state_file)
        except FileNotFoundError:
            pass

    def _fetch_manifest(self, timeout=20):
        req = urllib.request.Request(self._url("manifest.json"), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return modpack_format.validate_manifest(json.loads(resp.read().decode("utf-8")))

    def _mods_present(self):
        return any((Path(self.mods_path) / name).is_dir() for name in self._owned_folders())

    def _refresh_versions(self):
        settings = dict(self.settings)
        if not settings["modpack_url"]:
            self.root.after(0, lambda: self.version_label.config(text="일반 게임 실행 · 모드팩 URL을 설정하면 업데이트도 사용할 수 있습니다."))
            return
        cur = self._read_version()
        latest = None
        try:
            latest = self._fetch_manifest(timeout=8).get("latest_version")
        except Exception:
            pass
        cur_s = f"v{cur}" if cur is not None else ("설치됨(버전미상)" if self._mods_present() else "미설치")
        latest_s = f"v{latest}" if latest is not None else "확인불가"
        if latest is not None and cur is not None and cur >= latest:
            msg = f"현재 {cur_s} · 최신 {latest_s}  (최신 상태)"
        else:
            msg = f"현재 {cur_s} · 최신 {latest_s}"
        if settings == self.settings:
            self.root.after(0, lambda: self.version_label.config(text=msg))

    # ── Steam / PZ 탐색 ───────────────────────

    def _find_steam_path(self):
        try:
            import winreg
            for hive, subkey, val in [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            ]:
                try:
                    key = winreg.OpenKey(hive, subkey)
                    path = winreg.QueryValueEx(key, val)[0]
                    winreg.CloseKey(key)
                    if os.path.isdir(path):
                        return path
                except OSError:
                    continue
        except ImportError:
            pass
        for p in [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam",
                   r"D:\Steam", r"E:\Steam", r"D:\SteamLibrary"]:
            if os.path.isdir(p):
                return p
        return None

    def _find_steam_libraries(self):
        libs = [self.steam_path]
        vdf = os.path.join(self.steam_path, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            with open(vdf, encoding="utf-8") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    p = m.group(1).replace("\\\\", "\\")
                    if os.path.isdir(p) and p not in libs:
                        libs.append(p)
        return libs

    def _find_pz(self):
        for lib in self.steam_libraries:
            manifest = os.path.join(lib, "steamapps", f"appmanifest_{PZ_APP_ID}.acf")
            if not os.path.isfile(manifest):
                continue
            with open(manifest, encoding="utf-8") as f:
                txt = f.read()
            idir = re.search(r'"installdir"\s+"([^"]+)"', txt)
            if idir:
                path = os.path.join(lib, "steamapps", "common", idir.group(1))
                if os.path.isdir(path):
                    self.pz_install_path = path
                    return True
        return False

    def _find_workshop_mods(self):
        self.workshop_paths = workshop_cleanup.find_workshop_roots(self.steam_libraries)
        items = []
        for ws in self.workshop_paths:
            items.extend(path for path in ws.iterdir() if path.is_dir())
        return items

    # ── 버튼 핸들러 ────────────────────────────

    def _on_launch(self):
        credentials = None
        if self.settings["server_host"]:
            try:
                username, password = (entry.get() for entry in self.connection_entries)
                credentials = server_connect.validate(self.settings["server_host"], self.settings["server_port"],
                                                       username, password, self.settings["server_password"])
            except ValueError as exc:
                messagebox.showerror("접속 정보 확인", str(exc))
                return
        self._start(lambda: self._run_launch(credentials))

    def _on_remove(self):
        self._start(self._run_remove)

    def _managed_path(self):
        return Path(self.state_file).parent / "_modpack_managed.json"

    def _remember_managed(self, manifest, folders=None):
        digests = manifest.get("digests") if isinstance(manifest, dict) else None
        names = sorted(digests) if isinstance(digests, dict) else sorted(folders or [])
        for name in names:
            modpack_format.folder_name(name)
        game_runtime._atomic_write(self._managed_path(),
            (json.dumps({"folders": names}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def _run_remove(self):
        game_runtime.ensure_game_stopped()
        if not self.settings["game_path"]:
            self._step_check_steam()
        self._step_check_pz()
        ownership = self._managed_path()
        if not ownership.is_file():
            self._log("이 모드팩의 설치 기록이 없습니다. 제거할 파일이 없습니다.")
            return
        folders = self._owned_folders()
        existing = [name for name in folders if (Path(self.mods_path) / name).is_dir()]
        details = "\n".join(existing[:8]) + ("\n…" if len(existing) > 8 else "")
        if not self._ask_on_main(lambda: messagebox.askyesno(
                "서버 모드팩 제거",
                f"이 모드팩의 모드 {len(existing)}개를 제거할까요?\n\n"
                f"{details}\n\n세이브와 별도로 추가한 모드는 보존합니다.")):
            return
        result = modpack_remove.remove_modpack(self.pz_install_path, self.mods_path,
            self.lua_dir, self.state_file, folders, managed_file=ownership)
        server_connect.cleanup(self.pz_install_path, self.lua_dir)
        self._log(f"서버 모드팩 제거 완료: {len(result['removed'])}개")
        self.root.after(0, self._set_progress, 100, "서버 모드팩 제거 완료")
        self._ask_on_main(lambda: messagebox.showinfo(
            "제거 완료", "모드팩을 제거했습니다. 게임 파일과 세이브는 보존했습니다."))

    def _launch_log_path(self):
        return Path(self.state_file).parent / "pz-launcher.log"

    def _open_launch_log(self):
        path = self._launch_log_path()
        if path.is_file():
            os.startfile(str(path))
        else:
            messagebox.showinfo("실행 로그", "아직 게임 실행 로그가 없습니다.")

    def _run_launch(self, credentials=None):
        self._launching = True
        try:
            self._pre_checks()
            if self.settings["modpack_url"]:
                self._run_update(prepared=True)
            log_path = self._launch_log_path()
            self._log("게임 시작 중...")
            self._log(f"실행 로그: {log_path}")
            if credentials is not None:
                server_connect.prepare(self.pz_install_path, self.lua_dir, credentials)
            else:
                server_connect.cleanup(self.pz_install_path, self.lua_dir)
            try:
                process = game_launch.launch_game(self.pz_install_path, log_path,
                                                java_agent=self.settings["java_agent"],
                                                java_agent_options=self.settings["java_agent_options"])
            except Exception:
                if credentials is not None:
                    server_connect.cleanup(self.pz_install_path, self.lua_dir)
                raise
            self.game_process = process
            # JVM startup errors can happen before console.txt exists.
            deadline = time.monotonic() + 3
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            if process.poll() is not None:
                self.game_process = None
                if credentials is not None:
                    server_connect.cleanup(self.pz_install_path, self.lua_dir)
                raise RuntimeError(f"게임이 시작 직후 종료됐습니다 (코드 {process.returncode}). "
                                   f"실행 로그를 확인해주세요: {log_path}")
            self._log("게임 프로세스를 시작했습니다. 게임을 종료하면 다시 업데이트할 수 있습니다.")
            self.root.after(0, self._set_progress, 100, "게임 실행 중")
            def watch():
                code = process.wait()
                if credentials is not None:
                    try:
                        server_connect.cleanup(self.pz_install_path, self.lua_dir)
                    except OSError:
                        self._log("접속 임시 파일 정리에 실패했습니다. 모드팩 제거 시 다시 정리합니다.")
                def ended():
                    if self.game_process is not process:
                        return
                    self.game_process = None
                    self._set_buttons(True)
                    self._set_progress(100, "게임 종료")
                    self._log(f"게임 종료 (코드 {code}) — 로그: {log_path}")
                    if code:
                        messagebox.showerror("게임 종료", f"게임이 오류로 종료됐습니다 (코드 {code}).\n{log_path}")
                try:
                    self.root.after(0, ended)
                except RuntimeError:
                    pass  # The user closed the launcher while playing.
            threading.Thread(target=watch, daemon=True).start()
        finally:
            self._launching = False

    def _on_full(self):
        # 버튼 콜백은 메인 스레드 → messagebox 직접 호출 (_ask_on_main 쓰면 데드락)
        if not messagebox.askyesno(
                "전체 재설치",
                "전체 모드팩을 새로 내려받아 설치합니다.\n"
                "이 모드팩의 기존 모드를 교체합니다. 개인 모드와 세이브는 보존합니다. 계속할까요?"):
            return
        self._start(self._run_full)

    def _on_update(self):
        self._start(self._run_update)

    def _on_manual(self):
        path = filedialog.askopenfilename(
            title="모드팩 zip 파일 선택",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(
                "수동 설치",
                "선택한 zip 으로 모드를 설치합니다.\n"
                "이 모드팩의 기존 모드를 교체합니다. 개인 모드와 세이브는 보존합니다. 계속할까요?"):
            return
        self._start(lambda: self._run_manual(path))

    def _start(self, action):
        if self._busy:
            return
        self._busy = True
        self._set_buttons(False)
        self._total_bytes = 0
        self._set_progress(0, "")

        def run():
            try:
                action()
            except _AbortInstall:
                pass
            except urllib.error.URLError as e:
                detail = self._display_text(e)
                self._log(f"\n네트워크 오류: {detail}")
                self.root.after(0, lambda detail=detail: messagebox.showerror(
                    "네트워크 오류", f"서버에 연결할 수 없습니다.\n\n{detail}"))
            except Exception as e:
                detail = self._display_text(e)
                self._log(f"\n오류: {detail}")
                self.root.after(0, lambda detail=detail: messagebox.showerror("오류", detail))
            finally:
                def finished():
                    self._busy = False
                    self._set_buttons(True)
                self.root.after(0, finished)
                self._refresh_in_background()

        threading.Thread(target=run, daemon=True).start()

    # ── 공통 단계 ──────────────────────────────

    def _abort(self, check_key, msg, detail=""):
        self._set_check(check_key, "fail")
        self._log(f"[실패] {msg}")
        self._ask_on_main(
            lambda: messagebox.showerror("오류", f"{msg}\n\n{detail}" if detail else msg))
        raise _AbortInstall()

    def _pre_checks(self):
        game_runtime.ensure_game_stopped()
        if not self.settings["game_path"] or self.settings["force_workshop_delete"]:
            self._step_check_steam()
        self._step_check_pz()
        self._step_check_workshop()

    def _step_check_steam(self):
        self._set_check("steam", "wait")
        self._log("Steam 경로 탐색 중...")
        self.steam_path = self._find_steam_path()
        if not self.steam_path:
            self._abort("steam", "Steam을 찾을 수 없습니다.",
                        "Steam이 설치되어 있는지 확인해주세요.")
        self.steam_libraries = self._find_steam_libraries()
        self._set_check("steam", "ok")
        self._log(f"  Steam: {self.steam_path}")

    def _step_check_pz(self):
        self._set_check("pz_install", "wait")
        self._log("Project Zomboid 설치 확인 중...")
        configured = self.settings["game_path"]
        if configured:
            self._set_check("steam", "ok")
            self.pz_install_path = configured
            if not (Path(configured) / game_runtime.CONFIG_NAME).is_file():
                self._abort("pz_install", "지정한 게임 폴더에 ProjectZomboid64.json이 없습니다.")
        elif not self._find_pz():
            self._abort("pz_install",
                        "Project Zomboid가 설치되어 있지 않습니다.",
                        "Steam에서 Project Zomboid를 먼저 설치해주세요.")
        self._set_check("pz_install", "ok")
        self._log(f"  PZ 경로: {self.pz_install_path}")

    def _step_check_workshop(self):
        self._set_check("workshop", "wait")
        ws_items = self._find_workshop_mods()
        if not self.settings["force_workshop_delete"]:
            self._set_check("workshop", "warn" if ws_items else "ok")
            self._log(f"창작마당 모드 {len(ws_items)}개 확인 — 구독 모드와 같은 ID의 로컬 모드를 함께 사용하지 마세요.")
            return
        try:
            roots = workshop_cleanup.validate_workshop_roots(self.workshop_paths)
            if not roots:
                self._set_check("workshop", "ok")
                self._log("삭제할 좀보이드 워크샵 캐시가 없습니다.")
                return
            targets = "\n".join(str(path) for path in roots)
            confirmed = self._ask_on_main(lambda: messagebox.askyesno(
                "워크샵 강제 삭제",
                f"좀보이드 워크샵 모드 {len(ws_items)}개를 포함한 캐시 폴더를 삭제합니다.\n\n{targets}\n\n"
                "워크샵 구독은 해제되지 않으며 Steam에서 다시 다운로드할 수 있습니다.\n"
                "이 삭제는 되돌릴 수 없습니다. 계속할까요?",
                icon="warning", default="no", parent=self.root))
            if not confirmed:
                self._set_check("workshop", "warn")
                self._log("워크샵 삭제를 취소하여 실행·설치를 중단했습니다.")
                raise _AbortInstall()
            self._log("좀보이드 워크샵 캐시 삭제 중...")
            removed = workshop_cleanup.remove_workshop(roots)
        except (OSError, ValueError, RuntimeError):
            self._set_check("workshop", "fail")
            raise
        self._set_check("workshop", "ok")
        self._log(f"좀보이드 워크샵 캐시 {len(removed)}개 경로를 삭제했습니다.")

    # ── 다운로드 / 압축 유틸 ──────────────────

    def _download(self, url, dest, label):
        """url → dest 로 스트리밍 다운로드. 진행률 표시 + 누적 트래픽 집계."""
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = int(resp.getheader("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                self._total_bytes += len(chunk)
                if total:
                    pct = min(done / total * 100, 100)
                    self.root.after(0, self._set_progress, pct,
                                    f"{label}  {done/1048576:.1f}/{total/1048576:.1f} MB ({pct:.0f}%)")
                else:
                    self.root.after(0, self._set_progress, 0,
                                    f"{label}  {done/1048576:.1f} MB")
        return done

    def _extract_zip(self, zip_path, label="압축 해제 중..."):
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = modpack_format.archive_members(zf)
            total = len(members)
            for i, member in enumerate(members, 1):
                zf.extract(member, self.mods_path)
                if i % max(1, total // 50) == 0 or i == total:
                    pct = i / total * 100
                    self.root.after(0, self._set_progress, pct, f"{label} {i}/{total} ({pct:.0f}%)")

    def _fix_nested(self):
        nested = os.path.join(self.mods_path, "mods")
        if os.path.isdir(nested) and len(os.listdir(self.mods_path)) == 1:
            for item in os.listdir(nested):
                shutil.move(os.path.join(nested, item),
                            os.path.join(self.mods_path, item))
            os.rmdir(nested)
            self._log("  중첩 폴더 구조 보정 완료")

    @staticmethod
    def _find_mod_info(mod_root):
        """mod.info 를 찾는다. B42 모드는 루트에 mod.info 가 없는 경우가 많다.

        B42 부터 모드가 <모드폴더>/42.20/, /42/, /common/ 처럼 버전 폴더로 나뉘고
        mod.info 도 그 안에만 있는 배포본이 흔하다. 루트만 보면 id 를 못 뽑아서
        modmanager-mods.txt 에서 통째로 빠지고, 접속자는 "다운로드는 됐는데
        모드가 안 켜져요" 를 겪는다. (LGExtendedPlumbing, ZomboidForge,
        Mod Manager, Simple Belt Flashlight+, The Last of Us Infected 등이 해당)

        게임 로더와 같은 우선순위로 찾는다: 42.x 중 가장 높은 것 -> 42 -> common -> 루트.
        """
        candidates = []
        try:
            entries = sorted(os.listdir(mod_root))
        except OSError:
            entries = []

        versioned = []
        for name in entries:
            if not os.path.isdir(os.path.join(mod_root, name)):
                continue
            parts = name.split(".")
            if all(p.isdigit() for p in parts) and parts and parts[0] == "42":
                versioned.append((tuple(int(p) for p in parts), name))
        versioned.sort(reverse=True)
        candidates.extend(name for _, name in versioned)
        if "common" in entries:
            candidates.append("common")
        candidates.append(None)

        for sub in candidates:
            path = (os.path.join(mod_root, sub, "mod.info") if sub
                    else os.path.join(mod_root, "mod.info"))
            if os.path.isfile(path):
                return path
        return None

    def _regen_modlist(self):
        """설치된 모든 모드의 mod.info → modmanager-mods.txt 재생성."""
        self._log("모드 활성화 목록 갱신 중...")
        installed = [
            d for d in os.listdir(self.mods_path)
            if os.path.isdir(os.path.join(self.mods_path, d))]
        mod_ids = []
        missing = []
        for mod_dir in installed:
            info = self._find_mod_info(os.path.join(self.mods_path, mod_dir))
            if info:
                found = False
                with open(info, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        m = re.match(r"^id\s*=\s*(.+)", line.strip())
                        if m:
                            mod_ids.append(m.group(1).strip())
                            found = True
                            break
                if not found:
                    missing.append(mod_dir)
            else:
                missing.append(mod_dir)
        if missing:
            # 조용히 빠지면 원인을 못 찾는다. 어떤 폴더가 빠졌는지 남긴다.
            self._log("  ! mod.info 를 못 찾은 폴더: " + ", ".join(missing))
        if mod_ids:
            os.makedirs(self.lua_dir, exist_ok=True)
            modlist_path = os.path.join(self.lua_dir, "modmanager-mods.txt")
            with open(modlist_path, "w", encoding="utf-8") as f:
                f.write("VERSION=1\n")
                f.write(";".join(mod_ids) + "\n")
            self._log(f"  {len(mod_ids)}개 모드 활성화")
        return len(installed), len(mod_ids)

    # ── 전체 설치 ──────────────────────────────

    def _owned_folders(self):
        path = self._managed_path()
        if not path.is_file():
            return []
        values = json.loads(path.read_text(encoding="utf-8"))["folders"]
        if not isinstance(values, list):
            raise ValueError("모드팩 설치 기록이 올바르지 않습니다.")
        return [modpack_format.folder_name(name) for name in values]

    def _merge_personal_mods(self, staged):
        live = Path(self.mods_path)
        owned = {name.casefold() for name in self._owned_folders()}
        incoming = {p.name.casefold() for p in staged.iterdir()}
        if not live.exists():
            return
        if live.is_symlink():
            raise ValueError("링크된 모드 폴더에는 자동 설치할 수 없습니다.")
        for child in live.iterdir():
            if child.is_symlink() or (child.is_dir() and any(p.is_symlink() for p in child.rglob("*"))):
                raise ValueError("링크된 모드 파일에는 자동 설치할 수 없습니다.")
            if child.name.casefold() in owned:
                continue
            if child.name.casefold() in incoming:
                raise ValueError(f"개인 모드와 이름이 겹칩니다: {child.name}. 해당 폴더를 백업 후 옮겨주세요.")
            if child.is_dir():
                shutil.copytree(child, staged / child.name)
            else:
                shutil.copy2(child, staged / child.name)

    def _commit_mods(self, staged, manifest=None, version=None, managed_folders=None):
        """Keep the old tree and runtime files until every installation step succeeds."""
        live = Path(self.mods_path)
        tracked = [Path(self.state_file), Path(self.lua_dir) / "modmanager-mods.txt", self._managed_path()]
        originals = {path: path.read_bytes() if path.exists() else None for path in tracked}
        backup = Path(tempfile.mkdtemp(prefix=".pz-install-backup-", dir=live.parent))
        moved_old = installed_new = False
        cleanup = True
        try:
            # Preserve recovery data on disk as well as in memory in case rollback fails.
            for i, data in enumerate(originals.values()):
                if data is not None:
                    (backup / str(i)).write_bytes(data)
            (backup / "restore.json").write_text(json.dumps([
                {"path": str(path), "backup": str(i) if data is not None else None}
                for i, (path, data) in enumerate(originals.items())], indent=2), encoding="utf-8")
            if live.exists():
                os.replace(live, backup / "mods")
                moved_old = True
            os.replace(staged, live)
            installed_new = True
            counts = self._regen_modlist()
            if counts[1] == 0:
                raise ValueError("설치할 모드의 mod.info를 찾지 못했습니다.")
            self._clear_version()
            if version is not None:
                self._write_version(version)
            self._remember_managed(manifest, folders=managed_folders)
            return counts
        except Exception:
            try:
                if installed_new:
                    shutil.rmtree(live)
                if moved_old:
                    os.replace(backup / "mods", live)
                for path, data in originals.items():
                    if data is None:
                        path.unlink(missing_ok=True)
                    elif not path.exists() or path.read_bytes() != data:
                        game_runtime._atomic_write(path, data)
            except Exception as rollback_error:
                cleanup = False
                try:
                    self._clear_version()
                except OSError:
                    pass
                raise RuntimeError(f"설치 복구를 완료하지 못했습니다. 백업: {backup}") from rollback_error
            raise
        finally:
            if cleanup:
                shutil.rmtree(backup, ignore_errors=True)

    def _stage_archive(self, archive, staged, require_mods=False, expected_folder=None):
        if expected_folder:
            with zipfile.ZipFile(archive) as zf:
                members = modpack_format.archive_members(zf)
                if not members or any(item.filename.split("/")[0] != expected_folder for item in members):
                    raise ValueError("개별 모드 ZIP의 폴더가 배포 정보와 다릅니다.")
        original = self.mods_path
        self.mods_path = str(staged)
        try:
            self._extract_zip(archive)
            self._fix_nested()
            if require_mods and not any(
                    child.is_dir() and self._find_mod_info(str(child))
                    for child in Path(staged).iterdir()):
                raise ValueError("선택한 ZIP에 설치 가능한 모드가 없습니다.")
        finally:
            self.mods_path = original

    def _full_install(self, manifest):
        parent = Path(self.mods_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        # Extraction verifies ZIP CRCs in a separate tree; failures leave the live install intact.
        with tempfile.TemporaryDirectory(prefix=".pz-full-", dir=parent) as temp:
            zip_path = Path(temp) / "mods.zip"
            staged = Path(temp) / "mods"
            staged.mkdir()
            self._log("전체 모드팩 다운로드 중...")
            self._download(self._archive_url(manifest, "mods.zip"), str(zip_path), "다운로드 중...")
            modpack_format.verify_archive(zip_path, manifest, "mods.zip")
            self._stage_archive(zip_path, staged, require_mods=True)
            names = [p.name for p in staged.iterdir() if p.is_dir()]
            if manifest and "digests" in manifest and set(names) != set(manifest["digests"]):
                raise ValueError("전체 모드 ZIP의 폴더가 배포 정보와 다릅니다.")
            self._merge_personal_mods(staged)
            v = manifest.get("latest_version") if manifest else None
            n_mod, n_id = self._commit_mods(staged, manifest, version=v, managed_folders=names)
        self._finish(f"전체 설치 완료! 모드 {n_mod}개 / 활성화 {n_id}개"
                     + (f" (v{v})" if v is not None else ""))

    def _run_full(self):
        self._pre_checks()
        manifest = None
        try:
            manifest = self._fetch_manifest()
        except Exception:
            self._log("  (manifest 확인 실패 — 버전 기록 없이 진행)")
        self._full_install(manifest)

    def _run_manual(self, src_zip):
        self._pre_checks()
        if not os.path.isfile(src_zip):
            self._abort("steam", "선택한 zip 파일을 찾을 수 없습니다.", src_zip)
        parent = Path(self.mods_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".pz-manual-", dir=parent) as temp:
            staged = Path(temp) / "mods"
            staged.mkdir()
            self._log(f"로컬 zip 설치 중: {os.path.basename(src_zip)}")
            self._stage_archive(src_zip, staged, require_mods=True)
            names = [p.name for p in staged.iterdir() if p.is_dir()]
            self._merge_personal_mods(staged)
            n_mod, n_id = self._commit_mods(staged, managed_folders=names)
        # 로컬 zip 의 실제 버전은 서버의 최신 버전으로 추정할 수 없다.
        # 버전 미확정 상태를 유지해 다음 업데이트에서 전체 설치로 복구한다.
        self._finish(f"수동 설치 완료! 모드 {n_mod}개 / 활성화 {n_id}개"
                     " (버전 미확인 — 다음 업데이트는 전체 설치)")

    # ── 증분 업데이트 ──────────────────────────

    def _diff(self, manifest, cur):
        """cur 버전 이후 변경분 누적 — 모드별 '마지막 동작'(변경/삭제)만 남김."""
        action = {}
        for v in sorted(manifest.get("versions", []), key=lambda x: x.get("version", 0)):
            if v.get("version", 0) <= cur:
                continue
            for m in v.get("changed", []):
                action[m] = "changed"
            for m in v.get("removed", []):
                action[m] = "removed"
        changed = sorted(m for m, a in action.items() if a == "changed")
        removed = sorted(m for m, a in action.items() if a == "removed")
        return changed, removed

    def _run_update(self, prepared=False):
        if not prepared:
            self._pre_checks()
        self._log("서버에서 업데이트 정보 확인 중...")
        manifest = self._fetch_manifest()
        latest = int(manifest.get("latest_version", 0))
        cur = self._read_version()

        # 첫 설치 / 모드 폴더 없음 → 전체 설치
        if cur is None or not self._mods_present():
            self._log("설치 버전을 확인할 수 없거나 모드팩이 없어 전체 설치를 진행합니다.")
            self._full_install(manifest)
            return

        if cur >= latest:
            self._set_progress(100, f"최신 버전 (v{cur})")
            self._log(f"이미 최신 버전입니다 (v{cur}).")
            if not getattr(self, "_launching", False):
                self._ask_on_main(lambda: messagebox.showinfo(
                    "최신 버전", f"이미 최신 버전입니다 (v{cur})."))
            return

        changed, removed = self._diff(manifest, cur)
        owned = set(self._owned_folders())
        for folder in changed + removed:
            modpack_format.folder_name(folder)
            if (Path(self.mods_path) / folder).exists() and folder not in owned:
                raise ValueError(f"개인 모드와 이름이 겹칩니다: {folder}. 자동 변경하지 않습니다.")
        if not changed and not removed:
            self._write_version(latest)
            self._log(f"변경된 모드가 없습니다. v{latest} 로 갱신.")
            return

        self._log(f"v{cur} → v{latest} : 변경 {len(changed)}개, 삭제 {len(removed)}개")
        parent = Path(self.mods_path).parent
        if Path(self.mods_path).is_symlink() or any(p.is_symlink() for p in Path(self.mods_path).rglob("*")):
            raise ValueError("링크된 모드 폴더에는 자동 설치할 수 없습니다.")
        with tempfile.TemporaryDirectory(prefix=".pz-update-", dir=parent) as temp:
            staged = Path(temp) / "mods"
            shutil.copytree(self.mods_path, staged)
            tmp_zip = Path(temp) / "update.zip"
            total = len(changed)
            for i, folder in enumerate(changed, 1):
                self._log(f"  [{i}/{total}] {folder}")
                url = self._archive_url(manifest, "mods/" + urllib.parse.quote(folder, safe="") + ".zip")
                self._download(url, str(tmp_zip), f"[{i}/{total}] {folder}")
                modpack_format.verify_archive(tmp_zip, manifest, "mods/" + folder + ".zip")
                target = staged / folder
                if target.is_dir():
                    shutil.rmtree(target)
                self._stage_archive(tmp_zip, staged, expected_folder=folder)
            for folder in removed:
                target = staged / folder
                if target.is_dir():
                    shutil.rmtree(target)
            self._commit_mods(staged, manifest, version=latest, managed_folders=sorted((owned | set(changed)) - set(removed)))
        mb = self._total_bytes / 1048576
        self._finish(f"업데이트 완료! v{cur} → v{latest}  "
                     f"(변경 {len(changed)} / 삭제 {len(removed)}, 다운로드 {mb:.1f} MB)")

    # ── 마무리 ────────────────────────────────

    def _finish(self, summary):
        self.root.after(0, self._set_progress, 100, "완료!")
        self._log(f"\n{summary}")
        self._log(f"경로: {self.mods_path}")
        if getattr(self, "_launching", False):
            return
        self._ask_on_main(lambda: messagebox.showinfo(
            "완료",
            f"{summary}\n\n경로: {self.mods_path}\n\n"
            "이 런처의 '업데이트 후 게임 실행' 버튼으로 시작해주세요."))

    def run(self):
        self.root.mainloop()


class _AbortInstall(Exception):
    pass


if __name__ == "__main__":
    try:
        app = PZModInstaller()
    except (ValueError, OSError) as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("런처 설정 오류", str(exc))
        root.destroy()
        sys.exit(1)
    app.run()
