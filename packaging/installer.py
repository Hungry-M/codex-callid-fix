#!/usr/bin/env python3
"""Per-user installer for Codex Call ID Fix.

Build with packaging/build.ps1.  The payload (GUI exe, backend, Node runtime,
README) is embedded by PyInstaller as the `payload` data directory.

The installer:
  * copies the payload to %LOCALAPPDATA%\\Programs\\CodexCallIdFix
  * preserves an existing backend/callidfix.config.json on upgrade
  * creates Start Menu / Desktop shortcuts
  * registers an uninstall entry in HKCU
  * runs `manage.js status --json` and verifies the installed backend
  * optionally deletes itself after a successful install

Silent mode (used by the build tests):
  CodexCallIdFix-Setup-0.1.3.exe --silent --dir <dir> --no-shortcuts --no-registry --no-launch --keep-installer
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import sv_ttk  # type: ignore
except Exception:  # pragma: no cover
    sv_ttk = None

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - only on Windows
    winreg = None

APP_NAME = "Codex Call ID Fix"
APP_VERSION = "0.1.3"
AUTHOR = "Hungry-M"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexCallIdFix"

INSTALLER_LANG_LABELS = {"zh": "简体中文", "zh-Hant": "繁體中文", "en": "English"}
INSTALLER_LANG_BY_LABEL = {v: k for k, v in INSTALLER_LANG_LABELS.items()}

INSTALLER_STRINGS = {
    "zh": {
        "title": "Codex Call ID Fix {version} — 安装",
        "subtitle": "安装程序 {version}  ·  仅安装到当前用户，不需要管理员权限",
        "language": "语言",
        "appearance": "外观",
        "theme_system": "跟随系统",
        "theme_light": "浅色",
        "theme_dark": "深色",
        "location": "安装位置",
        "browse": "浏览…",
        "options": "选项",
        "desktop": "创建桌面快捷方式",
        "launch": "安装完成后启动 Codex Call ID Fix",
        "autodelete": "安装并自检成功后自动删除安装包",
        "start": "开始安装",
        "ready": "准备就绪。",
        "installing": "正在安装…",
        "installed": "安装完成，自检通过。",
        "failed": "安装失败，安装包未删除。",
        "log": "日志",
        "choose_dir": "请选择安装目录。",
        "create_dir_failed": "无法创建安装目录：{error}",
        "install_failed": "安装失败：\n\n{error}",
    },
    "zh-Hant": {
        "title": "Codex Call ID Fix {version} — 安裝",
        "subtitle": "安裝程式 {version}  ·  僅安裝到目前使用者，不需要系統管理員權限",
        "language": "語言",
        "appearance": "外觀",
        "theme_system": "跟隨系統",
        "theme_light": "淺色",
        "theme_dark": "深色",
        "location": "安裝位置",
        "browse": "瀏覽…",
        "options": "選項",
        "desktop": "建立桌面捷徑",
        "launch": "安裝完成後啟動 Codex Call ID Fix",
        "autodelete": "安裝並自檢成功後自動刪除安裝套件",
        "start": "開始安裝",
        "ready": "準備就緒。",
        "installing": "正在安裝…",
        "installed": "安裝完成，自檢通過。",
        "failed": "安裝失敗，安裝套件未刪除。",
        "log": "記錄",
        "choose_dir": "請選擇安裝目錄。",
        "create_dir_failed": "無法建立安裝目錄：{error}",
        "install_failed": "安裝失敗：\n\n{error}",
    },
    "en": {
        "title": "Codex Call ID Fix {version} — Install",
        "subtitle": "Installer {version}  ·  Per-user install, no administrator rights required",
        "language": "Language",
        "appearance": "Appearance",
        "theme_system": "Follow system",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "location": "Install location",
        "browse": "Browse…",
        "options": "Options",
        "desktop": "Create a desktop shortcut",
        "launch": "Launch Codex Call ID Fix after installing",
        "autodelete": "Delete this installer after a successful self-check",
        "start": "Install",
        "ready": "Ready.",
        "installing": "Installing…",
        "installed": "Installed; self-check passed.",
        "failed": "Install failed; the installer was kept.",
        "log": "Log",
        "choose_dir": "Choose an install folder.",
        "create_dir_failed": "Could not create the install folder: {error}",
        "install_failed": "Installation failed:\n\n{error}",
    },
}


def installer_tr(lang: str, key: str, **kwargs) -> str:
    table = INSTALLER_STRINGS.get(lang) or INSTALLER_STRINGS["en"]
    value = table.get(key) or INSTALLER_STRINGS["en"].get(key) or key
    try:
        return value.format(**kwargs)
    except Exception:
        return value


def detect_installer_language() -> str:
    if os.name == "nt":
        try:
            import ctypes

            langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0xFFFF
            if (langid & 0x3FF) == 0x04:
                return "zh-Hant" if langid in (0x0404, 0x0C04, 0x1404) else "zh"
            return "en"
        except Exception:
            pass
    try:
        import locale

        code = (locale.getdefaultlocale()[0] or "").lower()
        if code.startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Programs" / "CodexCallIdFix"
    return Path.home() / "CodexCallIdFix"


def payload_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "payload"
    return Path(__file__).resolve().parent / "stage"


def backup_root() -> Path:
    override = os.environ.get("CALLIDFIX_BACKUP_ROOT")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "CodexCallIdFix" / "backups"
    return Path.home() / "CodexCallIdFix" / "backups"


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def create_install_backup(install_dir: Path, log) -> Path:
    """Snapshot existing tool data plus Codex config/.env before installation."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = backup_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{stamp}-v{APP_VERSION}"
    suffix = 1
    while target.exists():
        suffix += 1
        target = root / f"{stamp}-v{APP_VERSION}-{suffix}"
    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    # Existing install's user data (upgrade case).
    for rel in (
        "backend/callidfix.config.json",
        "backend/state.json",
        "backend/gui.json",
        "backend/node-path.txt",
    ):
        source = install_dir / rel
        if not source.is_file():
            continue
        dest = target / "install" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(f"install/{rel}")

    # Codex files that this tool may modify after installation.
    codex = codex_home()
    for name in (
        "config.toml",
        ".env",
        ".env.callidfix-parked",
        ".env.callidfix-backup",
    ):
        source = codex / name
        if not source.is_file():
            continue
        dest = target / "codex" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(f"codex/{name}")

    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app": APP_NAME,
        "version": APP_VERSION,
        "install_dir": str(install_dir),
        "codex_home": str(codex),
        "files": copied,
        "note": (
            "Automatic pre-install backup. Uninstall runs manage.js off to "
            "restore tool-managed config.toml base_url and .env changes; "
            "this snapshot is for manual recovery and is removed only after "
            "a successful uninstall."
        ),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(f"自动备份：{target}（{len(copied)} 个文件）")
    return target


def run_capture(args: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 60):
    """Run a command with file-based stdio (sandbox friendly)."""
    with tempfile.TemporaryDirectory(prefix="callidfix-installer-") as tmp:
        out_path = Path(tmp) / "out.txt"
        err_path = Path(tmp) / "err.txt"
        with open(out_path, "wb") as out_file, open(err_path, "wb") as err_file:
            proc = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out_file,
                stderr=err_file,
                creationflags=CREATE_NO_WINDOW,
                timeout=timeout,
            )
        stdout = out_path.read_bytes().decode("utf-8", errors="replace")
        stderr = err_path.read_bytes().decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


def copy_payload(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise RuntimeError(f"安装包内缺少 payload：{src}")
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Do not overwrite the user's runtime configuration on upgrade.
        if rel.as_posix() == "backend/callidfix.config.json" and target.exists():
            continue
        shutil.copy2(item, target)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(shortcut: Path, target: Path, workdir: Path, icon: Path) -> None:
    if os.name != "nt":
        return
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$ws = New-Object -ComObject WScript.Shell",
            f"$s = $ws.CreateShortcut({_powershell_quote(str(shortcut))})",
            f"$s.TargetPath = {_powershell_quote(str(target))}",
            f"$s.WorkingDirectory = {_powershell_quote(str(workdir))}",
            f"$s.IconLocation = {_powershell_quote(str(icon))}",
            f"$s.Description = {_powershell_quote(APP_NAME)}",
            "$s.Save()",
            "",
        ]
    )
    with tempfile.TemporaryDirectory(prefix="callidfix-shortcut-") as tmp:
        ps1 = Path(tmp) / "shortcut.ps1"
        ps1.write_text(script, encoding="utf-8-sig")
        code, out, err = run_capture(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
            ],
            timeout=30,
        )
    if code != 0:
        raise RuntimeError(f"创建快捷方式失败：{err or out}")


def write_uninstaller(install_dir: Path) -> None:
    uninstall_ps1 = install_dir / "uninstall.ps1"
    uninstall_cmd = install_dir / "uninstall.cmd"
    script = f"""$ErrorActionPreference = 'SilentlyContinue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$node = Join-Path $dir 'runtime\\node.exe'
$manage = Join-Path $dir 'backend\\manage.js'
$restoreCode = 1
if ((Test-Path $node) -and (Test-Path $manage)) {{
    & $node $manage off
    $restoreCode = $LASTEXITCODE
}}
if ($restoreCode -ne 0) {{
    $backupRootFile = Join-Path $dir 'backup-root.txt'
    $backupRoot = Join-Path $env:LOCALAPPDATA 'CodexCallIdFix'
    if (Test-Path $backupRootFile) {{ $backupRoot = (Get-Content -LiteralPath $backupRootFile -Raw).Trim() }}
    Add-Type -AssemblyName System.Windows.Forms
    $message = "Could not restore Codex config.toml/.env automatically.`nThe installation and backup were kept.`n`nFix the reported provider URL issue, then run uninstall.cmd again.`n`nBackup: " + $backupRoot
    [System.Windows.Forms.MessageBox]::Show($message, 'Codex Call ID Fix', 'OK', 'Warning') | Out-Null
    exit 1
}}
$trustSign = Join-Path $dir 'trust-sign.ps1'
if (Test-Path $trustSign) {{
    & powershell -NoProfile -ExecutionPolicy Bypass -File $trustSign -RemoveCert | Out-Null
}}
& $node $manage autostart off | Out-Null
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v codex-callid-fix /f 2>$null | Out-Null
Remove-Item -LiteralPath 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CodexCallIdFix' -Recurse -Force
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CodexCallIdFix" /f 2>$null | Out-Null
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')
Remove-Item -LiteralPath (Join-Path $desktop 'Codex Call ID Fix.lnk') -Force
Remove-Item -LiteralPath (Join-Path $programs 'Codex Call ID Fix.lnk') -Force
Remove-Item -LiteralPath (Join-Path $programs 'Trust & Sign Codex Call ID Fix.lnk') -Force
$backupRootFile = Join-Path $dir 'backup-root.txt'
$backupRoot = Join-Path $env:LOCALAPPDATA 'CodexCallIdFix'
if (Test-Path $backupRootFile) {{ $backupRoot = (Get-Content -LiteralPath $backupRootFile -Raw).Trim() }}
if ($backupRoot -and (Test-Path $backupRoot)) {{ Remove-Item -LiteralPath $backupRoot -Recurse -Force }}
$cleanup = Join-Path $env:TEMP ('codex-callid-fix-cleanup-' + [guid]::NewGuid().ToString() + '.cmd')
$cleanupLines = @(
    '@echo off',
    'timeout /t 2 >nul',
    ('rmdir /s /q "' + $dir + '"'),
    'del "%~f0"'
)
Set-Content -LiteralPath $cleanup -Value $cleanupLines -Encoding ASCII
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', ('"' + $cleanup + '"')) -WindowStyle Hidden
"""
    uninstall_ps1.write_text(script, encoding="utf-8-sig")
    uninstall_cmd.write_text(
        '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"\r\n',
        encoding="utf-8",
    )


def register_uninstall(install_dir: Path) -> None:
    if os.name != "nt":
        return
    gui = install_dir / "CodexCallIdFix.exe"
    icon = install_dir / "assets" / "app.ico"
    uninstall = install_dir / "uninstall.cmd"
    size_kb = 0
    for item in install_dir.rglob("*"):
        try:
            if item.is_file():
                size_kb += item.stat().st_size // 1024
        except OSError:
            pass

    values = [
        ("DisplayName", APP_NAME, "REG_SZ"),
        ("DisplayVersion", APP_VERSION, "REG_SZ"),
        ("Publisher", AUTHOR, "REG_SZ"),
        ("InstallLocation", str(install_dir), "REG_SZ"),
        ("DisplayIcon", str(icon if icon.exists() else gui), "REG_SZ"),
        ("UninstallString", f'"{uninstall}"', "REG_SZ"),
        ("QuietUninstallString", f'"{uninstall}"', "REG_SZ"),
        ("InstallDate", time.strftime("%Y%m%d"), "REG_SZ"),
        ("EstimatedSize", str(int(size_kb)), "REG_DWORD"),
        ("NoModify", "1", "REG_DWORD"),
        ("NoRepair", "1", "REG_DWORD"),
    ]

    # Native winreg is the normal path, but some hardened/AV environments
    # deny it to unsigned onefile EXEs. Fall back to reg.exe.
    if winreg is not None:
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE
            )
            try:
                for name, value, kind in values:
                    if kind == "REG_DWORD":
                        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            finally:
                key.Close()
            return
        except OSError:
            pass

    for name, value, kind in values:
        code, out, err = run_capture(
            [
                "reg",
                "add",
                f"HKCU\\{UNINSTALL_KEY}",
                "/v",
                name,
                "/t",
                kind,
                "/d",
                value,
                "/f",
            ],
            timeout=20,
        )
        if code != 0:
            raise RuntimeError(
                f"registry write failed ({name}): {err or out}".strip()
            )


def shell_folder(name: str, fallback: Path) -> Path:
    """Resolve Desktop/Programs via User Shell Folders (OneDrive-aware)."""
    if winreg is not None and os.name == "nt":
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            try:
                value, _ = winreg.QueryValueEx(key, name)
            finally:
                key.Close()
            resolved = os.path.expandvars(str(value))
            if resolved:
                return Path(resolved)
        except Exception:
            pass
    return fallback


def refresh_autostart(install_dir: Path, log) -> None:
    """Keep a previously enabled autostart entry pointing at this install."""
    if winreg is None or os.name != "nt":
        return
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        try:
            winreg.QueryValueEx(key, "codex-callid-fix")
        finally:
            key.Close()
    except OSError:
        return

    node = install_dir / "runtime" / "node.exe"
    manage = install_dir / "backend" / "manage.js"
    try:
        env = os.environ.copy()
        env["CALLIDFIX_DATA_DIR"] = str(install_dir / "backend")
        code, out, err = run_capture(
            [str(node), str(manage), "autostart", "on"], env=env, timeout=30
        )
        if code != 0:
            log(f"更新自启动项失败（可忽略）：{err or out}")
    except Exception as exc:  # noqa: BLE001
        log(f"更新自启动项失败（可忽略）：{exc}")


def verify_install(install_dir: Path) -> dict:
    gui = install_dir / "CodexCallIdFix.exe"
    node = install_dir / "runtime" / "node.exe"
    manage = install_dir / "backend" / "manage.js"
    for path in (
        gui,
        node,
        manage,
        install_dir / "backend" / "rewrite.js",
        install_dir / "README.md",
        install_dir / "README.zh.md",
        install_dir / "README.zh-Hant.md",
        install_dir / "AUTHORS.md",
        install_dir / "LICENSE",
        install_dir / "THIRD_PARTY_NOTICES.md",
        install_dir / "third_party" / "Node-LICENSE.txt",
        install_dir / "SECURITY.md",
        install_dir / "trust-sign.ps1",
        install_dir / "trust-sign.cmd",
    ):
        if not path.exists():
            raise RuntimeError(f"安装校验失败，缺少文件：{path}")

    env = os.environ.copy()
    env["CALLIDFIX_DATA_DIR"] = str(install_dir / "backend")
    code, out, err = run_capture(
        [str(node), str(manage), "status", "--json"], env=env, timeout=45
    )
    if code != 0:
        raise RuntimeError(f"安装校验失败（status 退出码 {code}）：{err or out}")
    try:
        status = json.loads(out.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"安装校验失败，状态输出不是 JSON：{exc}") from exc
    if status.get("version") != APP_VERSION:
        raise RuntimeError(
            f"安装校验失败，版本不匹配：{status.get('version')} != {APP_VERSION}"
        )
    return status


def install(
    install_dir: Path,
    *,
    shortcuts: bool = True,
    registry: bool = True,
    log=None,
) -> Path:
    log = log or (lambda _message: None)
    src = payload_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    backup = create_install_backup(install_dir, log)
    (install_dir / "backup-root.txt").write_text(
        str(backup.parent) + "\n", encoding="utf-8"
    )

    log(f"复制文件到 {install_dir} …")
    copy_payload(src, install_dir)

    log("写入卸载程序 …")
    write_uninstaller(install_dir)

    gui = install_dir / "CodexCallIdFix.exe"
    icon = install_dir / "assets" / "app.ico"
    if shortcuts and os.name == "nt":
        log("创建快捷方式 …")
        try:
            desktop = shell_folder(
                "Desktop", Path(os.environ.get("USERPROFILE", "")) / "Desktop"
            )
            programs = shell_folder(
                "Programs",
                Path(os.environ.get("APPDATA", ""))
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs",
            )
            if desktop.is_dir():
                create_shortcut(desktop / f"{APP_NAME}.lnk", gui, install_dir, icon)
            create_shortcut(programs / f"{APP_NAME}.lnk", gui, install_dir, icon)
            create_shortcut(
                programs / "Trust & Sign Codex Call ID Fix.lnk",
                install_dir / "trust-sign.cmd",
                install_dir,
                icon,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"快捷方式创建失败（可忽略）：{exc}")

    if registry and os.name == "nt":
        log("注册卸载信息 …")
        try:
            register_uninstall(install_dir)
        except Exception as exc:  # noqa: BLE001
            # Some hardened environments deny registry writes to unsigned
            # onefile EXEs. The app is still usable and uninstall.cmd exists.
            log(f"卸载注册表项写入失败（不影响使用，可用 uninstall.cmd 卸载）：{exc}")

    log("运行自检 …")
    status = verify_install(install_dir)
    log(
        f"自检通过：v{status.get('version')}，"
        f"{len(status.get('provider', {}).get('providers', []))} 个 provider，"
        f"代理当前 {'ON' if status.get('state', {}).get('enabled') else 'OFF'}。"
    )
    refresh_autostart(install_dir, log)
    return install_dir


def schedule_self_delete() -> None:
    if not getattr(sys, "frozen", False):
        return
    installer = Path(sys.executable)
    cleanup = Path(tempfile.gettempdir()) / (
        f"codex-callid-fix-installer-cleanup-{os.getpid()}.cmd"
    )
    cleanup.write_text(
        "\r\n".join(
            [
                "@echo off",
                "timeout /t 3 >nul",
                f'del /f /q "{installer}"',
                'del "%~f0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(cleanup)],
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        pass


def launch_app(install_dir: Path) -> None:
    gui = install_dir / "CodexCallIdFix.exe"
    try:
        subprocess.Popen([str(gui)], cwd=str(install_dir), close_fds=True)
    except Exception:
        pass


class InstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.installing = False
        self.success_dir: Path | None = None
        self.auto_delete = tk.BooleanVar(value=True)
        self.desktop_shortcut = tk.BooleanVar(value=True)
        self.launch_after = tk.BooleanVar(value=True)
        self.install_dir_var = tk.StringVar(value=str(default_install_dir()))
        self.lang = detect_installer_language()
        self.theme_mode = "system"
        self.dark = self._system_is_dark()
        self.root.title(self.t("title", version=APP_VERSION))
        self.root.geometry("680x560")
        self.root.minsize(620, 520)
        self.root.resizable(True, True)

        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if self.dark else "light")
        self._build()
        self._apply_icon()
        self._apply_theme()

    def t(self, key: str, **kwargs) -> str:
        return installer_tr(self.lang, key, **kwargs)

    def _rebuild(self) -> None:
        if self.installing:
            return
        for child in self.root.winfo_children():
            child.destroy()
        self._build()
        self._apply_icon()
        self._apply_theme()

    def on_language_changed(self, _event=None) -> None:
        lang = INSTALLER_LANG_BY_LABEL.get(self.lang_combo.get(), self.lang)
        if lang == self.lang:
            return
        self.lang = lang
        self.root.title(self.t("title", version=APP_VERSION))
        self._rebuild()

    def _system_is_dark(self) -> bool:
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            finally:
                key.Close()
            return int(value) == 0
        except Exception:
            return False

    def _effective_dark(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        return self._system_is_dark()

    def on_theme_changed(self, _event=None) -> None:
        mode = {
            self.t("theme_system"): "system",
            self.t("theme_light"): "light",
            self.t("theme_dark"): "dark",
        }.get(self.theme_combo.get(), "system")
        self.theme_mode = mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.dark = self._effective_dark()
        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if self.dark else "light")
        bg = "#1b1b1f" if self.dark else "#f4f4f5"
        fg = "#f4f4f5" if self.dark else "#18181b"
        try:
            self.root.configure(bg=bg)
            self.log_text.configure(bg=bg, fg=fg, insertbackground=fg)
        except Exception:
            pass

    def _apply_icon(self) -> None:
        try:
            icon = payload_dir() / "assets" / "app.ico"
            if icon.is_file():
                self.root.iconbitmap(default=str(icon))
            png = payload_dir() / "assets" / "app.png"
            if png.is_file():
                photo = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, photo)
                self.root._app_icon = photo  # type: ignore[attr-defined]
        except Exception:
            pass

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(22, 18, 22, 4))
        header.pack(fill="x")
        ttk.Label(header, text=f"{APP_NAME}", font=("Segoe UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text=self.t("subtitle", version=APP_VERSION) + f"  ·  by {AUTHOR}",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        settings_frame = ttk.Frame(header)
        settings_frame.place(relx=1.0, y=0, anchor="ne")

        ttk.Label(settings_frame, text=self.t("language"), font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="e", padx=(0, 6)
        )
        self.lang_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            width=10,
            values=list(INSTALLER_LANG_LABELS.values()),
        )
        self.lang_combo.set(INSTALLER_LANG_LABELS[self.lang])
        self.lang_combo.grid(row=0, column=1, sticky="e")
        self.lang_combo.bind("<<ComboboxSelected>>", self.on_language_changed)

        ttk.Label(settings_frame, text=self.t("appearance"), font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=(4, 0)
        )
        self.theme_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            width=10,
            values=[
                self.t("theme_system"),
                self.t("theme_light"),
                self.t("theme_dark"),
            ],
        )
        self.theme_combo.set(
            {
                "system": self.t("theme_system"),
                "light": self.t("theme_light"),
                "dark": self.t("theme_dark"),
            }.get(self.theme_mode, self.t("theme_system"))
        )
        self.theme_combo.grid(row=1, column=1, sticky="e", pady=(4, 0))
        self.theme_combo.bind("<<ComboboxSelected>>", self.on_theme_changed)

        path_card = ttk.LabelFrame(self.root, text=self.t("location"), padding=14)
        path_card.pack(fill="x", padx=22, pady=(12, 4))
        path_card.columnconfigure(0, weight=1)
        ttk.Entry(path_card, textvariable=self.install_dir_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(path_card, text=self.t("browse"), command=self.browse).grid(
            row=0, column=1, padx=(8, 0)
        )

        options = ttk.LabelFrame(self.root, text=self.t("options"), padding=14)
        options.pack(fill="x", padx=22, pady=4)
        ttk.Checkbutton(
            options, text=self.t("desktop"), variable=self.desktop_shortcut
        ).pack(anchor="w")
        ttk.Checkbutton(
            options, text=self.t("launch"), variable=self.launch_after
        ).pack(anchor="w")
        ttk.Checkbutton(
            options,
            text=self.t("autodelete"),
            variable=self.auto_delete,
        ).pack(anchor="w")

        action = ttk.Frame(self.root, padding=(22, 8, 22, 0))
        action.pack(fill="x")
        self.install_button = ttk.Button(
            action, text=self.t("start"), style="Accent.TButton", command=self.start_install
        )
        self.install_button.pack(side="left")
        self.progress = ttk.Progressbar(action, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(
            self.root, textvariable=self.status_var, wraplength=620, padding=(22, 8)
        ).pack(fill="x")

        log_frame = ttk.LabelFrame(self.root, text=self.t("log"), padding=8)
        log_frame.pack(fill="both", expand=True, padx=22, pady=(0, 14))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=7,
            wrap="word",
            relief="flat",
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def browse(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            initialdir=str(Path(self.install_dir_var.get()).parent),
            title=self.t("location"),
        )
        if selected:
            self.install_dir_var.set(selected)

    def start_install(self) -> None:
        if self.installing:
            return
        target = Path(self.install_dir_var.get().strip())
        if not target:
            messagebox.showerror(APP_NAME, self.t("choose_dir"), parent=self.root)
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME, self.t("create_dir_failed", error=exc), parent=self.root
            )
            return

        self.installing = True
        self.install_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set(self.t("installing"))
        self.log(f"{self.t('location')}: {target}")

        def worker() -> None:
            try:
                install(
                    target,
                    shortcuts=bool(self.desktop_shortcut.get()),
                    registry=True,
                    log=lambda msg: self.queue.put(("log", msg)),
                )
                self.queue.put(("done", target))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(120, self.poll)

    def poll(self) -> None:
        try:
            kind, payload = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(120, self.poll)
            return

        if kind == "log":
            self.log(str(payload))
            self.root.after(120, self.poll)
            return

        self.progress.stop()
        self.installing = False
        if kind == "error":
            self.install_button.configure(state="normal")
            self.status_var.set(self.t("failed"))
            self.log(f"{self.t('install_failed', error=payload)}")
            messagebox.showerror(
                APP_NAME, self.t("install_failed", error=payload), parent=self.root
            )
            return

        target = Path(payload)
        self.success_dir = target
        self.status_var.set(self.t("installed"))
        self.log(self.t("installed"))
        if self.launch_after.get():
            launch_app(target)
        self.root.after(1400, self.finish)

    def finish(self) -> None:
        if self.auto_delete.get():
            schedule_self_delete()
        self.root.destroy()

    def on_close(self) -> None:
        if self.installing:
            return
        if self.auto_delete.get() and self.success_dir is not None:
            schedule_self_delete()
        self.root.destroy()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--dir", default=None)
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-registry", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--keep-installer", action="store_true")
    parser.add_argument("--result-file", default=None)
    return parser.parse_args(argv)


def write_result(path: str | None, payload: dict) -> None:
    if not path:
        return
    try:
        result_path = Path(path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _safe_print(message: str) -> None:
    """Best-effort stdout for windowed --silent runs (stdout may be invalid)."""
    try:
        print(message, flush=True)
    except Exception:
        pass


def silent_install(args: argparse.Namespace) -> int:
    target = Path(args.dir) if args.dir else default_install_dir()
    log_lines: list[str] = []

    def log(message: str) -> None:
        log_lines.append(message)
        _safe_print(message)

    try:
        install(
            target,
            shortcuts=not args.no_shortcuts,
            registry=not args.no_registry,
            log=log,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        _safe_print(f"INSTALL_FAILED: {exc}")
        write_result(
            args.result_file,
            {
                "ok": False,
                "error": str(exc),
                "dir": str(target),
                "log": log_lines,
                "traceback": traceback.format_exc(),
            },
        )
        return 1
    if not args.no_launch:
        launch_app(target)
    if not args.keep_installer:
        schedule_self_delete()
    _safe_print(f"INSTALL_OK {target}")
    write_result(
        args.result_file,
        {"ok": True, "dir": str(target), "version": APP_VERSION, "log": log_lines},
    )
    return 0


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.silent:
        return silent_install(args)

    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
