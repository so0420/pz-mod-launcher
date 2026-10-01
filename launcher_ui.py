"""A small, neutral Tk interface with optional server and Java-agent settings."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import launcher_config

BG, PANEL, TEXT, MUTED, ACCENT = "#f5f6f8", "#ffffff", "#20252d", "#667085", "#2563eb"
FONT = "맑은 고딕"


def build(app):
    root = app.root
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TButton", font=(FONT, 10), padding=(12, 9))
    style.configure("Primary.TButton", background=ACCENT, foreground="white", font=(FONT, 11, "bold"))
    style.map("Primary.TButton", background=[("disabled", "#cbd5e1"), ("active", "#1d4ed8")])
    style.configure("TEntry", padding=6, fieldbackground=PANEL, font=(FONT, 10))
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e5e7eb", borderwidth=0)

    def label(parent, text, size=10, color=TEXT, bold=False):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), anchor="w")

    main = tk.Frame(root, bg=BG)
    main.pack(fill="both", expand=True, padx=24, pady=22)
    header = tk.Frame(main, bg=BG)
    header.pack(fill="x")
    app.title_label = label(header, app.settings["title"], 20, bold=True)
    app.title_label.pack(side="left")
    app.settings_btn = ttk.Button(header, text="설정", command=lambda: settings_dialog(app))
    app.settings_btn.pack(side="right")
    app.version_label = label(main, "버전 확인 중...", color=MUTED)
    app.version_label.pack(fill="x", pady=(4, 14))

    checks = tk.Frame(main, bg=PANEL, padx=12, pady=10)
    checks.pack(fill="x")
    app.checks = {}
    for key, title in [("steam", "Steam"), ("pz_install", "게임 파일"), ("workshop", "창작마당 모드")]:
        row = tk.Frame(checks, bg=PANEL)
        row.pack(side="left", expand=True, fill="x")
        icon = label(row, "·", color=MUTED)
        icon.pack(side="left", padx=(0, 6))
        label(row, title, color=MUTED).pack(side="left")
        app.checks[key] = icon

    app.account_card = tk.Frame(main, bg=PANEL, padx=14, pady=12)
    app.account_card.pack(fill="x", pady=(12, 0))
    app.server_label = label(app.account_card, "서버 접속", bold=True)
    app.server_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    app.connection_entries = []
    for row, (title, masked) in enumerate([
            ("게임 계정명", False), ("계정 비밀번호", True)], 1):
        label(app.account_card, title, 9, MUTED).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=3)
        entry = ttk.Entry(app.account_card, show="*" if masked else "", font=(FONT, 10))
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        app.connection_entries.append(entry)
    app.account_card.columnconfigure(1, weight=1)
    label(app.account_card, "Steam 계정이 아닌 서버용 계정입니다. 계정 비밀번호는 저장하지 않습니다.", 8, MUTED).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))

    log_heading = tk.Frame(main, bg=BG)
    app.log_heading = log_heading
    log_heading.pack(fill="x", pady=(14, 7))
    label(log_heading, "진행 내역", bold=True).pack(side="left")
    ttk.Button(log_heading, text="실행 로그 열기", command=app._open_launch_log).pack(side="right")
    logs = tk.Frame(main, bg=PANEL)
    logs.pack(fill="both", expand=True)
    app.log_text = tk.Text(logs, height=6, state="disabled", bg=PANEL, fg=TEXT, relief="flat",
                           font=(FONT, 9), wrap="word", padx=12, pady=10, spacing1=3)
    scroll = ttk.Scrollbar(logs, command=app.log_text.yview)
    app.log_text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    app.log_text.pack(side="left", fill="both", expand=True)
    app.progress = ttk.Progressbar(main, maximum=100)
    app.progress.pack(fill="x", pady=(12, 4))
    app.progress_label = label(main, "준비됐습니다.", 9, MUTED)
    app.progress_label.pack(fill="x")
    app.launch_btn = ttk.Button(main, text="게임 실행", command=app._on_launch, style="Primary.TButton")
    app.launch_btn.pack(fill="x", pady=(12, 8))
    utilities = tk.Frame(main, bg=BG)
    utilities.pack(fill="x")
    app.update_btn = ttk.Button(utilities, text="모드 업데이트", command=app._on_update)
    app.full_btn = ttk.Button(utilities, text="모드팩 재설치", command=app._on_full)
    app.manual_btn = ttk.Button(utilities, text="ZIP 수동 설치", command=app._on_manual)
    for col, button in enumerate([app.update_btn, app.full_btn, app.manual_btn]):
        utilities.columnconfigure(col, weight=1, uniform="actions")
        button.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0 if col == 2 else 4))
    footer = tk.Frame(main, bg=BG)
    footer.pack(fill="x", pady=(10, 0))
    app.remove_btn = ttk.Button(footer, text="이 모드팩 제거", command=app._on_remove)
    app.remove_btn.pack(side="left")
    ttk.Button(footer, text="닫기", command=app._close).pack(side="right")
    app.action_btns = [app.full_btn, app.update_btn, app.manual_btn, app.launch_btn, app.remove_btn, app.settings_btn]
    refresh(app)


def refresh(app):
    settings = app.settings
    app.root.title(settings["title"])
    app.title_label.configure(text=settings["title"])
    host = settings["server_host"]
    if host:
        app.account_card.pack(fill="x", pady=(12, 0), before=app.log_heading)
    else:
        app.account_card.pack_forget()
    app.server_label.configure(text="서버 접속" if host else "서버 접속 (선택)")
    for entry in app.connection_entries:
        entry.configure(state="normal" if host else "disabled")
    verb = "서버 접속" if host else "게임 실행"
    app.launch_btn.configure(text=("업데이트 후 " if settings["modpack_url"] else "") + verb)
    app.update_btn.configure(state="normal" if settings["modpack_url"] else "disabled")
    app.full_btn.configure(state="normal" if settings["modpack_url"] else "disabled")
    if not host:
        app.server_label.configure(text="서버 접속 · 설정에서 서버 주소를 지정할 수 있습니다.")


def settings_dialog(app):
    dialog = tk.Toplevel(app.root)
    dialog.title("런처 설정")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.transient(app.root)
    dialog.grab_set()
    form = tk.Frame(dialog, bg=BG, padx=20, pady=18)
    form.pack(fill="both", expand=True)
    entries = {}
    address_fields = {"modpack_url", "server_host", "server_port"}
    fields = [("title", "런처 이름"), ("pack_id", "모드팩 ID"), ("modpack_url", "모드팩 URL (선택)"),
              ("server_host", "게임 서버 주소 (선택)"), ("server_port", "서버 포트"),
              ("game_path", "게임 폴더 (자동 탐지 가능)"), ("java_agent", "Java 패치 JAR (선택)"),
              ("java_agent_options", "Java 패치 옵션 (선택)")]
    for row, (key, title) in enumerate(fields):
        tk.Label(form, text=title, bg=BG, fg=TEXT, font=(FONT, 9)).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
        entry = ttk.Entry(form, width=46, font=(FONT, 10), show="*" if key in address_fields else "")
        entry.insert(0, app.settings[key])
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        entries[key] = entry
        if key in ("game_path", "java_agent"):
            def browse(key=key):
                path = (filedialog.askdirectory(parent=dialog, title="게임 설치 폴더") if key == "game_path"
                        else filedialog.askopenfilename(parent=dialog, title="Java 패치 JAR 선택", filetypes=[("Java archive", "*.jar")]))
                if path:
                    entries[key].delete(0, "end")
                    entries[key].insert(0, path)
            ttk.Button(form, text="선택", command=browse).grid(row=row, column=2, padx=(8, 0))
    force_workshop_delete = tk.BooleanVar(dialog, value=app.settings["force_workshop_delete"])
    ttk.Checkbutton(form, text="워크샵 강제 삭제 (실행·설치 전 확인)", variable=force_workshop_delete).grid(
        row=len(fields), column=0, columnspan=3, sticky="w", pady=(12, 0))
    tk.Label(form, text="좀보이드 워크샵 캐시만 삭제합니다. 구독은 유지되며 Steam에서 다시 다운로드할 수 있습니다.",
             bg=BG, fg=MUTED, font=(FONT, 9)).grid(
        row=len(fields) + 1, column=0, columnspan=3, sticky="w", pady=(4, 0))
    tk.Label(form, text="주소를 비우면 일반 게임을 실행합니다. Java 패치 경로는 게임 폴더 기준 또는 절대 경로입니다.\n"
                         "모드팩 ID가 다르면 설치 기록을 따로 관리합니다. 설정에는 비밀번호를 저장하지 않습니다.",
             bg=BG, fg=MUTED, font=(FONT, 9), justify="left").grid(row=len(fields) + 2, column=0, columnspan=3, sticky="w", pady=(12, 16))
    show_addresses = tk.BooleanVar(dialog, value=False)

    def toggle_addresses():
        for key in address_fields:
            entries[key].configure(show="" if show_addresses.get() else "*")

    ttk.Checkbutton(form, text="주소 표시", variable=show_addresses, command=toggle_addresses).grid(
        row=len(fields) + 3, column=0, sticky="w")

    def commit():
        try:
            values = launcher_config.save(dict(app.settings, force_workshop_delete=force_workshop_delete.get(),
                                              **{key: entry.get() for key, entry in entries.items()}))
            app.settings = values
            app._configure_paths()
            for entry in app.connection_entries:
                entry.configure(state="normal")
                entry.delete(0, "end")
            refresh(app)
            app._refresh_in_background()
        except (ValueError, OSError) as exc:
            messagebox.showerror("설정 확인", str(exc), parent=dialog)
            return
        dialog.destroy()
    ttk.Button(form, text="저장", command=commit, style="Primary.TButton").grid(row=len(fields) + 3, column=1, sticky="e")
