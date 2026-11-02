#!/usr/bin/env python3
"""Tkinter desktop UI for Codex Call ID Fix.

The UI is a thin, friendly front-end over backend/manage.js.  It never edits
Codex config.toml or .env itself; all changes go through the CLI so the CLI and
the GUI can never disagree.

Run from the repository root:
    python gui/app.py

Packaged layout:
    CodexCallIdFix.exe
    backend/manage.js, server.js, ...
    runtime/node.exe
    README.md
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows
    winreg = None

try:
    import sv_ttk  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sv_ttk = None

APP_NAME = "Codex Call ID Fix"
APP_VERSION = "1.0.0"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0

LANG_LABELS = {"zh": "简体中文", "zh-Hant": "繁體中文", "en": "English"}
LANG_BY_LABEL = {v: k for k, v in LANG_LABELS.items()}


def tr(lang: str, key: str, **kwargs) -> str:
    table = STRINGS.get(lang) or STRINGS["en"]
    value = table.get(key) or STRINGS["en"].get(key) or key
    try:
        return value.format(**kwargs)
    except Exception:
        return value


# ---------------------------------------------------------------------------
# translations
# ---------------------------------------------------------------------------

STRINGS = {
    "zh": {
        "window_title": "Codex Call ID Fix {version}",
        "subtitle": "修复 function_call_output.call_id 缺失问题，不修改提示词。",
        "menu": "菜单",
        "menu_settings": "设置…",
        "menu_trust_sign": "本地信任并签名…",
        "trust_sign_confirm": "这会创建一个自签名证书，加入当前用户的受信任根和受信任发布者，并给已安装的 EXE 签名。\n只对本机当前 Windows 账户有效；不会让其他电脑信任它。\n\n签名时应用会关闭，完成后自动重新打开。继续吗？",
        "trust_sign_unavailable": "只有安装版的 CodexCallIdFix.exe 支持本地签名；源码运行模式不适用。",
        "trust_sign_missing": "找不到 trust-sign.ps1：{path}",
        "trust_sign_failed": "无法启动签名工具：{error}",
        "menu_open_data": "打开数据目录",
        "menu_readme": "README",
        "menu_about": "关于",
        "menu_exit": "退出",
        "settings_title": "设置",
        "settings_language": "界面语言",
        "settings_appearance": "外观",
        "theme_system": "跟随系统",
        "theme_light": "浅色",
        "theme_dark": "深色",
        "settings_font_zh": "中文字体",
        "settings_font_en": "英文字体",
        "settings_font_size": "字号",
        "settings_note": "中文界面使用中文字体，English 界面使用英文字体；切换语言后界面会重新加载。外观设置只影响本工具。",
        "save": "保存",
        "cancel": "取消",
        "about_title": "关于",
        "about_text": "{name} {version}\n\n本地修复 Codex Desktop 的 function_call_output.call_id 缺失问题。\n\nAuthor: Hungry-M\nMIT License",
        "provider_card": "Codex 模型供应商",
        "current_provider": "当前供应商",
        "openai_builtin": "OpenAI（内置）",
        "provider_note_active": "model: {model}   catalog: {catalog}。切换供应商后请在 Codex 里确认 model 是否匹配。",
        "provider_note_active_nocatalog": "model: {model}。切换供应商后请在 Codex 里确认 model 是否匹配。",
        "provider_note_builtin": "OpenAI（内置）：已删除 model_provider。",
        "provider_note_model": " 当前 model = {model}。",
        "provider_note_catalog": " model_catalog_json 仍指向 {catalog}，如报模型不存在请在 Codex 里改选模型。",
        "status_card": "状态",
        "status_fix_proxy": "修复代理",
        "status_local_address": "本地地址",
        "status_egress": "出站方式",
        "status_env": "Codex .env",
        "status_autostart": "自启动",
        "phase_on": "ON",
        "phase_off": "OFF",
        "running": "运行中 (pid {pid})",
        "stopped": "已停止",
        "on_not_running": "状态为 ON，但进程未响应",
        "port_held": "端口被 pid {pid} 占用",
        "reachable": "可达",
        "unreachable": "不可达",
        "env_active": "已启用代理变量",
        "env_parked": "已移出（.env 已停用）",
        "env_absent": "没有 .env",
        "env_direct": "无代理变量",
        "env_not_managed": "不管理",
        "route_fix": "Codex → 本地 {port} → {egress}",
        "route_upstream": "Codex → 上游代理 {host}:{port}",
        "route_direct": "Codex → 直接出站（不经修复代理）",
        "route_openai_suffix": "（当前为 OpenAI，内置流量不经过修复代理）",
        "control_card": "控制",
        "start_proxy": "启动修复代理",
        "stop_proxy": "停止修复代理",
        "autostart_label": "登录 Windows 时自动启动（隐藏窗口）",
        "codex_route": "Codex 出口",
        "route_fix_short": "修复代理（本地端口）",
        "route_upstream_short": "上游代理",
        "route_direct_short": "直接出站",
        "fix_egress": "修复代理出站",
        "egress_proxy": "上游代理",
        "egress_direct": "直连",
        "egress_auto": "自动回退",
        "settings_card": "端口与上游代理",
        "local_port": "本地监听端口",
        "auto": "自动",
        "upstream_host": "上游代理地址",
        "port": "端口",
        "save_apply": "保存并应用",
        "port_note": "端口没有写死：这里改完会写入 callidfix.config.json，并自动重启/重新应用代理。",
        "log_card": "日志",
        "refresh": "刷新状态",
        "footer_note": "改动 config.toml / .env 后需要完全退出并重启 Codex Desktop。",
        "invalid_port_digits": "端口必须是数字。",
        "invalid_port_range": "端口必须在 1–65535 之间。",
        "empty_proxy_host": "上游代理地址不能为空。",
        "config_not_found": "找不到配置文件：{path}",
        "config_read_failed": "配置文件读取失败：{error}",
        "config_write_failed": "配置文件写入失败：{error}",
        "backend_error": "无法启动后端：{error}\n\n请确认已安装 Node.js，或安装包中的 runtime/node.exe 存在。",
        "command_failed": "命令执行失败：manage.js {command}\n\n{message}",
        "sandbox_write_denied": "Codex 沙箱禁止写入 ~/.codex/config.toml。请从开始菜单或资源管理器启动本工具，不要在 Codex 终端/沙箱内启动；如果仍失败，请用管理员权限运行一次。\n\n原始错误：{message}",
        "open_folder_failed": "无法打开目录：{error}",
        "readme_missing": "README.md 不在安装目录中。",
        "readme_open_failed": "无法打开 README：{error}",
        "warning_prefix": "警告",
        "backend_status_failed": "无法读取状态：{error}",
        "action_start_proxy": "启动修复代理",
        "action_stop_proxy": "停止修复代理",
        "action_switch_provider": "切换供应商 -> {target}",
        "action_autostart_on": "启用自启动",
        "action_autostart_off": "关闭自启动",
        "action_route": "Codex 出口 -> {route}",
        "action_egress": "修复代理出站 -> {mode}",
        "action_save_ports": "保存端口设置",
        "free_port_failed": "无法选择空闲端口：{error}",
        "provider_switch_note": "已切换供应商。如 Codex 报模型不存在，请在 Codex 里选择匹配的 model。",
    },
    "zh-Hant": {
        "window_title": "Codex Call ID Fix {version}",
        "subtitle": "修復 function_call_output.call_id 遺失問題，不修改提示詞。",
        "menu": "選單",
        "menu_settings": "設定…",
        "menu_trust_sign": "本機信任並簽名…",
        "trust_sign_confirm": "這會建立自簽憑證，加入目前使用者的受信任根與受信任發行者，並替已安裝的 EXE 簽名。\n只對本機目前 Windows 帳戶有效；不會讓其他電腦信任它。\n\n簽名時應用程式會關閉，完成後自動重新開啟。要繼續嗎？",
        "trust_sign_unavailable": "只有安裝版的 CodexCallIdFix.exe 支援本機簽名；原始碼執行模式不適用。",
        "trust_sign_missing": "找不到 trust-sign.ps1：{path}",
        "trust_sign_failed": "無法啟動簽名工具：{error}",
        "menu_open_data": "開啟資料目錄",
        "menu_readme": "README",
        "menu_about": "關於",
        "menu_exit": "結束",
        "settings_title": "設定",
        "settings_language": "介面語言",
        "settings_appearance": "外觀",
        "theme_system": "跟隨系統",
        "theme_light": "淺色",
        "theme_dark": "深色",
        "settings_font_zh": "中文字型",
        "settings_font_en": "英文字型",
        "settings_font_size": "字型大小",
        "settings_note": "中文介面使用中文字型，English 介面使用英文字型；切換語言後介面會重新載入。外觀設定只影響本工具。",
        "save": "儲存",
        "cancel": "取消",
        "about_title": "關於",
        "about_text": "{name} {version}\n\n本機修復 Codex Desktop 的 function_call_output.call_id 遺失問題。\n\nAuthor: Hungry-M\nMIT License",
        "provider_card": "Codex 模型供應商",
        "current_provider": "目前供應商",
        "openai_builtin": "OpenAI（內建）",
        "provider_note_active": "model: {model}   catalog: {catalog}。切換供應商後請在 Codex 裡確認 model 是否相符。",
        "provider_note_active_nocatalog": "model: {model}。切換供應商後請在 Codex 裡確認 model 是否相符。",
        "provider_note_builtin": "OpenAI（內建）：已刪除 model_provider。",
        "provider_note_model": " 目前 model = {model}。",
        "provider_note_catalog": " model_catalog_json 仍指向 {catalog}，若回報模型不存在請在 Codex 裡改選模型。",
        "status_card": "狀態",
        "status_fix_proxy": "修復代理",
        "status_local_address": "本機位址",
        "status_egress": "出站方式",
        "status_env": "Codex .env",
        "status_autostart": "自動啟動",
        "phase_on": "ON",
        "phase_off": "OFF",
        "running": "執行中 (pid {pid})",
        "stopped": "已停止",
        "on_not_running": "狀態為 ON，但程式未回應",
        "port_held": "連接埠被 pid {pid} 佔用",
        "reachable": "可連線",
        "unreachable": "無法連線",
        "env_active": "已啟用代理變數",
        "env_parked": "已移出（.env 已停用）",
        "env_absent": "沒有 .env",
        "env_direct": "無代理變數",
        "env_not_managed": "不管理",
        "route_fix": "Codex → 本機 {port} → {egress}",
        "route_upstream": "Codex → 上游代理 {host}:{port}",
        "route_direct": "Codex → 直接出站（不經修復代理）",
        "route_openai_suffix": "（目前為 OpenAI，內建流量不經過修復代理）",
        "control_card": "控制",
        "start_proxy": "啟動修復代理",
        "stop_proxy": "停止修復代理",
        "autostart_label": "登入 Windows 時自動啟動（隱藏視窗）",
        "codex_route": "Codex 出口",
        "route_fix_short": "修復代理（本機連接埠）",
        "route_upstream_short": "上游代理",
        "route_direct_short": "直接出站",
        "fix_egress": "修復代理出站",
        "egress_proxy": "上游代理",
        "egress_direct": "直連",
        "egress_auto": "自動退回",
        "settings_card": "連接埠與上游代理",
        "local_port": "本機監聽連接埠",
        "auto": "自動",
        "upstream_host": "上游代理位址",
        "port": "連接埠",
        "save_apply": "儲存並套用",
        "port_note": "連接埠不是寫死的：修改後會寫入 callidfix.config.json，並自動重新啟動/重新套用代理。",
        "log_card": "記錄",
        "refresh": "重新整理狀態",
        "footer_note": "變更 config.toml / .env 後需要完全結束並重新啟動 Codex Desktop。",
        "invalid_port_digits": "連接埠必須是數字。",
        "invalid_port_range": "連接埠必須在 1–65535 之間。",
        "empty_proxy_host": "上游代理位址不能為空。",
        "config_not_found": "找不到設定檔：{path}",
        "config_read_failed": "設定檔讀取失敗：{error}",
        "config_write_failed": "設定檔寫入失敗：{error}",
        "backend_error": "無法啟動後端：{error}\n\n請確認已安裝 Node.js，或安裝包中的 runtime/node.exe 存在。",
        "command_failed": "命令執行失敗：manage.js {command}\n\n{message}",
        "sandbox_write_denied": "Codex 沙箱禁止寫入 ~/.codex/config.toml。請從開始選單或檔案總管啟動本工具，不要在 Codex 終端/沙箱內啟動；如果仍失敗，請用系統管理員權限執行一次。\n\n原始錯誤：{message}",
        "open_folder_failed": "無法開啟目錄：{error}",
        "readme_missing": "README.md 不在安裝目錄中。",
        "readme_open_failed": "無法開啟 README：{error}",
        "warning_prefix": "警告",
        "backend_status_failed": "無法讀取狀態：{error}",
        "action_start_proxy": "啟動修復代理",
        "action_stop_proxy": "停止修復代理",
        "action_switch_provider": "切換供應商 -> {target}",
        "action_autostart_on": "啟用自動啟動",
        "action_autostart_off": "關閉自動啟動",
        "action_route": "Codex 出口 -> {route}",
        "action_egress": "修復代理出站 -> {mode}",
        "action_save_ports": "儲存連接埠設定",
        "free_port_failed": "無法選擇空閒連接埠：{error}",
        "provider_switch_note": "已切換供應商。若 Codex 回報模型不存在，請在 Codex 裡選擇相符的 model。",
    },
    "en": {
        "window_title": "Codex Call ID Fix {version}",
        "subtitle": "Fix missing function_call_output.call_id without touching prompts.",
        "menu": "Menu",
        "menu_settings": "Settings…",
        "menu_trust_sign": "Trust & sign locally…",
        "trust_sign_confirm": "This creates a self-signed certificate, adds it to the current user's Trusted Root and Trusted Publishers, and signs the installed EXE.\nIt is only trusted for this Windows account; other machines will not trust it.\n\nThe app will close, be signed, and reopen automatically. Continue?",
        "trust_sign_unavailable": "Local signing is only available for the installed CodexCallIdFix.exe, not source runs.",
        "trust_sign_missing": "trust-sign.ps1 not found: {path}",
        "trust_sign_failed": "Could not start the signing tool: {error}",
        "menu_open_data": "Open data folder",
        "menu_readme": "README",
        "menu_about": "About",
        "menu_exit": "Exit",
        "settings_title": "Settings",
        "settings_language": "Language",
        "settings_appearance": "Appearance",
        "theme_system": "Follow system",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "settings_font_zh": "Chinese font",
        "settings_font_en": "English font",
        "settings_font_size": "Font size",
        "settings_note": "The Chinese UI uses the Chinese font; the English UI uses the English font. Changing the language reloads the UI. Appearance only affects this tool.",
        "save": "Save",
        "cancel": "Cancel",
        "about_title": "About",
        "about_text": "{name} {version}\n\nLocal workaround for Codex Desktop's missing function_call_output.call_id error.\n\nAuthor: Hungry-M\nMIT License",
        "provider_card": "Codex Model Provider",
        "current_provider": "Current provider",
        "openai_builtin": "OpenAI (built-in)",
        "provider_note_active": "model: {model}   catalog: {catalog}. Verify the model name in Codex after switching.",
        "provider_note_active_nocatalog": "model: {model}. Verify the model name in Codex after switching.",
        "provider_note_builtin": "OpenAI (built-in): model_provider was removed.",
        "provider_note_model": " Current model = {model}.",
        "provider_note_catalog": " model_catalog_json still points to {catalog}; pick an OpenAI model in Codex if the model is rejected.",
        "status_card": "Status",
        "status_fix_proxy": "Fix proxy",
        "status_local_address": "Local address",
        "status_egress": "Egress",
        "status_env": "Codex .env",
        "status_autostart": "Autostart",
        "phase_on": "ON",
        "phase_off": "OFF",
        "running": "Running (pid {pid})",
        "stopped": "Stopped",
        "on_not_running": "State is ON, but the process is not responding",
        "port_held": "Port held by pid {pid}",
        "reachable": "reachable",
        "unreachable": "unreachable",
        "env_active": "proxy variables active",
        "env_parked": "parked (.env disabled)",
        "env_absent": "no .env",
        "env_direct": "no proxy variables",
        "env_not_managed": "not managed",
        "route_fix": "Codex → local {port} → {egress}",
        "route_upstream": "Codex → upstream proxy {host}:{port}",
        "route_direct": "Codex → direct (fix proxy bypassed)",
        "route_openai_suffix": " (OpenAI traffic does not use the fix proxy)",
        "control_card": "Controls",
        "start_proxy": "Start fix proxy",
        "stop_proxy": "Stop fix proxy",
        "autostart_label": "Start automatically at Windows sign-in (hidden)",
        "codex_route": "Codex route",
        "route_fix_short": "Fix proxy (local port)",
        "route_upstream_short": "Upstream proxy",
        "route_direct_short": "Direct",
        "fix_egress": "Fix proxy egress",
        "egress_proxy": "Upstream proxy",
        "egress_direct": "Direct",
        "egress_auto": "Auto fallback",
        "settings_card": "Ports and upstream proxy",
        "local_port": "Local listen port",
        "auto": "Auto",
        "upstream_host": "Upstream proxy host",
        "port": "Port",
        "save_apply": "Save and apply",
        "port_note": "Ports are not hard-coded: changes are written to callidfix.config.json and the proxy is restarted/re-applied.",
        "log_card": "Log",
        "refresh": "Refresh status",
        "footer_note": "Restart Codex Desktop completely after changing config.toml / .env.",
        "invalid_port_digits": "Ports must be numbers.",
        "invalid_port_range": "Ports must be between 1 and 65535.",
        "empty_proxy_host": "Upstream proxy host cannot be empty.",
        "config_not_found": "Config file not found: {path}",
        "config_read_failed": "Could not read the config file: {error}",
        "config_write_failed": "Could not write the config file: {error}",
        "backend_error": "Could not start the backend: {error}\n\nMake sure Node.js is installed, or that runtime/node.exe exists in the installation.",
        "command_failed": "Command failed: manage.js {command}\n\n{message}",
        "sandbox_write_denied": "Codex's sandbox denies writes to ~/.codex/config.toml. Start this app from the Start Menu or Explorer, not from a Codex terminal/sandbox. If it still fails, run it once as administrator.\n\nRaw error: {message}",
        "open_folder_failed": "Could not open the folder: {error}",
        "readme_missing": "README.md is not in the installation folder.",
        "readme_open_failed": "Could not open README: {error}",
        "warning_prefix": "warning",
        "backend_status_failed": "Could not read status: {error}",
        "action_start_proxy": "Start fix proxy",
        "action_stop_proxy": "Stop fix proxy",
        "action_switch_provider": "Switch provider -> {target}",
        "action_autostart_on": "Enable autostart",
        "action_autostart_off": "Disable autostart",
        "action_route": "Codex route -> {route}",
        "action_egress": "Fix proxy egress -> {mode}",
        "action_save_ports": "Save port settings",
        "free_port_failed": "Could not pick a free port: {error}",
        "provider_switch_note": "Provider switched. If Codex reports an unknown model, choose a matching model in Codex.",
    },
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_backend(root: Path) -> Path:
    for base in (root, root.parent, root.parent.parent):
        candidate = base / "backend"
        if (candidate / "manage.js").is_file():
            return candidate
    return root


def resolve_node(root: Path) -> str | None:
    for base in (root, root.parent):
        for candidate in (base / "runtime" / "node.exe", base / "node.exe"):
            if candidate.is_file():
                return str(candidate)
    return shutil.which("node")


def resolve_readme(root: Path, lang: str = "en") -> Path | None:
    preferred = {
        "zh": "README.zh.md",
        "zh-Hant": "README.zh-Hant.md",
    }.get(lang, "README.md")
    for base in (root, root.parent):
        for candidate in (
            base / preferred,
            base / "README.md",
            base / "backend" / "README.md",
        ):
            if candidate.is_file():
                return candidate
    return None


def resolve_asset(root: Path, name: str) -> Path:
    for base in (root, root.parent):
        candidate = base / "assets" / name
        if candidate.is_file():
            return candidate
    return root / "assets" / name


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def detect_language() -> str:
    if os.name == "nt":
        try:
            import ctypes

            langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0xFFFF
            primary = langid & 0x3FF
            if primary == 0x04:  # Chinese
                if langid in (0x0404, 0x0C04, 0x1404):
                    return "zh-Hant"
                return "zh"
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


class Palette:
    def __init__(self, dark: bool):
        self.dark = dark
        if dark:
            self.bg = "#1b1b1f"
            self.card = "#252529"
            self.text = "#f4f4f5"
            self.muted = "#a1a1aa"
            self.border = "#3f3f46"
            self.accent = "#4f8cff"
            self.accent_hover = "#6aa0ff"
            self.green = "#2ea043"
            self.red = "#d9534f"
            self.log_bg = "#151518"
        else:
            self.bg = "#f4f4f5"
            self.card = "#ffffff"
            self.text = "#18181b"
            self.muted = "#5f6368"
            self.border = "#d4d4d8"
            self.accent = "#0b6bcb"
            self.accent_hover = "#0a5cb0"
            self.green = "#1a7f37"
            self.red = "#cf222e"
            self.log_bg = "#fafafa"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.base_dir = app_dir()
        self.backend_dir = resolve_backend(self.base_dir)
        self.data_dir = Path(os.environ.get("CALLIDFIX_DATA_DIR", self.backend_dir))
        self.node = resolve_node(self.base_dir)
        self.manage = self.backend_dir / "manage.js"
        self.env = os.environ.copy()
        self.env["CALLIDFIX_DATA_DIR"] = str(self.data_dir)

        self.pref_path = self.data_dir / "gui.json"
        self.prefs = self._load_prefs()
        self.lang = self.prefs["lang"]
        self.theme_mode = self.prefs["theme"]
        self.font_zh = self.prefs["font_zh"]
        self.font_en = self.prefs["font_en"]
        self.font_size = self.prefs["font_size"]
        self.dark = self._effective_dark()
        self.palette = Palette(self.dark)
        self._last_system_dark = self._system_is_dark()

        self.status: dict | None = None
        self.config: dict | None = None
        self.config_path: Path = self.data_dir / "callidfix.config.json"
        self.busy = False
        self.work_queue: queue.Queue = queue.Queue()
        self._provider_display: dict[str, str | None] = {}
        self._suppress_provider_event = False
        self._suppress_autostart_event = False
        self._suppress_setting_events = False

        self._create_fonts()
        self._setup_style()
        self._build_ui()
        self._apply_palette()
        self.refresh_status(initial=True)
        self.root.after(5000, self._poll_system_theme)

    # ------------------------------------------------------------------ i18n
    def t(self, key: str, **kwargs) -> str:
        return tr(self.lang, key, **kwargs)

    def _load_prefs(self) -> dict:
        default_lang = detect_language()
        defaults = {
            "lang": default_lang,
            "theme": "system",
            "font_zh": "",
            "font_en": "Segoe UI",
            "font_size": 10,
        }
        try:
            data = json.loads(self.pref_path.read_text(encoding="utf-8"))
            if data.get("lang") in LANG_LABELS:
                defaults["lang"] = data["lang"]
            if data.get("theme") in ("system", "light", "dark"):
                defaults["theme"] = data["theme"]
            if isinstance(data.get("font_zh"), str):
                defaults["font_zh"] = data["font_zh"]
            if isinstance(data.get("font_en"), str):
                defaults["font_en"] = data["font_en"]
            try:
                size = int(data.get("font_size", 10))
                if 8 <= size <= 22:
                    defaults["font_size"] = size
            except Exception:
                pass
        except Exception:
            pass
        return defaults

    def _save_prefs(self) -> None:
        try:
            self.pref_path.parent.mkdir(parents=True, exist_ok=True)
            self.pref_path.write_text(
                json.dumps(
                    {
                        "lang": self.lang,
                        "theme": self.theme_mode,
                        "font_zh": self.font_zh,
                        "font_en": self.font_en,
                        "font_size": self.font_size,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _system_is_dark(self) -> bool:
        if os.name != "nt" or winreg is None:
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

    # ------------------------------------------------------------------ fonts
    def _default_font_zh(self) -> str:
        families = set(tkfont.families(self.root))
        if self.lang == "zh-Hant":
            candidates = ("Microsoft JhengHei UI", "Microsoft JhengHei", "MingLiU", "PMingLiU")
        else:
            candidates = ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun")
        for name in candidates:
            if name in families:
                return name
        return "Segoe UI"

    def _create_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        if not self.font_zh or self.font_zh not in families:
            self.font_zh = self._default_font_zh()
        if not self.font_en or self.font_en not in families:
            self.font_en = "Segoe UI" if "Segoe UI" in families else "TkDefaultFont"
        family = self.font_zh if self.lang.startswith("zh") else self.font_en
        size = max(8, min(22, int(self.font_size)))
        self.font_ui = tkfont.Font(root=self.root, family=family, size=size)
        self.font_small = tkfont.Font(root=self.root, family=family, size=max(8, size - 1))
        self.font_header = tkfont.Font(
            root=self.root, family=family, size=size + 10, weight="bold"
        )
        self.font_route = tkfont.Font(
            root=self.root, family=family, size=size + 3, weight="bold"
        )
        self.font_button = tkfont.Font(
            root=self.root, family=family, size=size + 2, weight="bold"
        )
        log_family = "Consolas" if "Consolas" in families else self.font_en
        self.font_mono = tkfont.Font(
            root=self.root, family=log_family, size=max(8, size - 1)
        )

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if self.dark else "light")
        else:
            style.theme_use("clam")
        style.configure(".", font=self.font_ui)
        style.configure("Header.TLabel", font=self.font_header)
        style.configure("Sub.TLabel", font=self.font_small)
        style.configure("Card.TLabelframe", padding=12)
        style.configure("Card.TLabelframe.Label", font=self.font_small)
        style.configure("Accent.TButton", font=self.font_small)
        style.configure("Route.TLabel", font=self.font_route)
        style.configure("Value.TLabel", font=self.font_mono)
        style.configure("Menu.TMenubutton", font=self.font_ui)

    def apply_settings(self, data: dict) -> None:
        self.lang = data["lang"]
        self.theme_mode = data["theme"]
        self.font_zh = data["font_zh"]
        self.font_en = data["font_en"]
        self.font_size = data["font_size"]
        self._save_prefs()
        self.dark = self._effective_dark()
        self.palette = Palette(self.dark)
        self._create_fonts()
        self._setup_style()
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        self._apply_palette()
        self.refresh_status()

    def open_settings(self) -> None:
        SettingsDialog(self)

    # --------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        root = self.root
        root.title(self.t("window_title", version=APP_VERSION))
        height = min(1080, 900 + max(0, int(self.font_size) - 10) * 16)
        root.geometry(f"1000x{height}")
        root.minsize(900, 760)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(5, weight=1)

        header = ttk.Frame(root, padding=(18, 14, 18, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Codex Call ID Fix", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text=self.t("subtitle"), style="Sub.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )

        self.menu_button = ttk.Menubutton(
            header, text=self.t("menu"), style="Menu.TMenubutton"
        )
        self.menu_button.grid(row=0, column=1, rowspan=2, sticky="e")
        menu = tk.Menu(self.menu_button, tearoff=False)
        menu.add_command(label=self.t("menu_settings"), command=self.open_settings)
        menu.add_command(label=self.t("menu_trust_sign"), command=self.trust_sign)
        menu.add_command(label=self.t("menu_open_data"), command=self.open_data_folder)
        menu.add_command(label=self.t("menu_readme"), command=self.open_readme)
        menu.add_separator()
        menu.add_command(label=self.t("menu_about"), command=self.show_about)
        menu.add_command(label=self.t("menu_exit"), command=self.root.destroy)
        self.menu_button.configure(menu=menu)

        # Provider card -----------------------------------------------------
        provider_card = ttk.LabelFrame(
            root, text=self.t("provider_card"), style="Card.TLabelframe"
        )
        provider_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(8, 4))
        provider_card.columnconfigure(1, weight=1)

        ttk.Label(provider_card, text=self.t("current_provider")).grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.provider_combo = ttk.Combobox(
            provider_card, state="readonly", width=44, values=[]
        )
        self.provider_combo.grid(row=0, column=1, sticky="ew")
        self.provider_combo.bind("<<ComboboxSelected>>", self.on_provider_changed)

        self.provider_note = ttk.Label(
            provider_card, text="—", style="Sub.TLabel", wraplength=860
        )
        self.provider_note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Status card -------------------------------------------------------
        status_card = ttk.LabelFrame(
            root, text=self.t("status_card"), style="Card.TLabelframe"
        )
        status_card.grid(row=2, column=0, sticky="ew", padx=18, pady=4)
        status_card.columnconfigure(1, weight=1)

        self.phase_label = tk.Label(
            status_card,
            text=self.t("phase_off"),
            padx=10,
            pady=4,
            font=self.font_small,
        )
        self.phase_label.grid(row=0, column=0, sticky="w")

        self.route_label = ttk.Label(
            status_card, text="—", style="Route.TLabel"
        )
        self.route_label.grid(row=0, column=1, sticky="w", padx=12)

        rows = [
            ("status_fix_proxy", "proxy_value"),
            ("status_local_address", "listen_value"),
            ("status_egress", "egress_value"),
            ("status_env", "env_value"),
            ("status_autostart", "autostart_value"),
        ]
        self.value_labels: dict[str, ttk.Label] = {}
        for index, (label_key, key) in enumerate(rows, start=1):
            ttk.Label(status_card, text=f"{self.t(label_key)}:").grid(
                row=index, column=0, sticky="w", pady=(4, 0)
            )
            value = ttk.Label(status_card, text="—", style="Value.TLabel")
            value.grid(row=index, column=1, sticky="w", padx=12, pady=(4, 0))
            self.value_labels[key] = value

        # Control card ------------------------------------------------------
        control_card = ttk.LabelFrame(
            root, text=self.t("control_card"), style="Card.TLabelframe"
        )
        control_card.grid(row=3, column=0, sticky="ew", padx=18, pady=4)
        control_card.columnconfigure(0, weight=2)
        control_card.columnconfigure(1, weight=1)
        control_card.columnconfigure(2, weight=1)

        left = ttk.Frame(control_card)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left.columnconfigure(0, weight=1)

        self.toggle_button = tk.Button(
            left,
            text=self.t("start_proxy"),
            command=self.on_toggle_proxy,
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            cursor="hand2",
            font=self.font_button,
        )
        self.toggle_button.grid(row=0, column=0, sticky="ew")

        self.autostart_var = tk.BooleanVar(value=False)
        self.autostart_check = ttk.Checkbutton(
            left,
            text=self.t("autostart_label"),
            variable=self.autostart_var,
            command=self.on_autostart_changed,
        )
        self.autostart_check.grid(row=1, column=0, sticky="w", pady=(10, 0))

        route_frame = ttk.Frame(control_card)
        route_frame.grid(row=0, column=1, sticky="nw", padx=(0, 12))
        ttk.Label(route_frame, text=self.t("codex_route")).grid(
            row=0, column=0, sticky="w"
        )
        self.route_var = tk.StringVar(value="direct")
        route_values = [
            ("fix", self.t("route_fix_short")),
            ("upstream", self.t("route_upstream_short")),
            ("direct", self.t("route_direct_short")),
        ]
        for index, (value, text) in enumerate(route_values, start=1):
            ttk.Radiobutton(
                route_frame,
                text=text,
                value=value,
                variable=self.route_var,
                command=lambda v=value: self.on_route_changed(v),
            ).grid(row=index, column=0, sticky="w", pady=(3, 0))

        egress_frame = ttk.Frame(control_card)
        egress_frame.grid(row=0, column=2, sticky="nw")
        ttk.Label(egress_frame, text=self.t("fix_egress")).grid(
            row=0, column=0, sticky="w"
        )
        self.egress_var = tk.StringVar(value="proxy")
        egress_values = [
            ("proxy", self.t("egress_proxy")),
            ("direct", self.t("egress_direct")),
            ("auto", self.t("egress_auto")),
        ]
        for index, (value, text) in enumerate(egress_values, start=1):
            ttk.Radiobutton(
                egress_frame,
                text=text,
                value=value,
                variable=self.egress_var,
                command=lambda v=value: self.on_egress_changed(v),
            ).grid(row=index, column=0, sticky="w", pady=(3, 0))

        # Settings card -----------------------------------------------------
        settings_card = ttk.LabelFrame(
            root, text=self.t("settings_card"), style="Card.TLabelframe"
        )
        settings_card.grid(row=4, column=0, sticky="ew", padx=18, pady=4)
        settings_card.columnconfigure(7, weight=1)

        ttk.Label(settings_card, text=self.t("local_port")).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.listen_port_var = tk.StringVar()
        self.listen_port_entry = ttk.Entry(
            settings_card, textvariable=self.listen_port_var, width=8
        )
        self.listen_port_entry.grid(row=0, column=1, sticky="w")
        self.auto_port_button = ttk.Button(
            settings_card, text=self.t("auto"), width=6, command=self.pick_free_port
        )
        self.auto_port_button.grid(row=0, column=2, padx=(4, 18))

        ttk.Label(settings_card, text=self.t("upstream_host")).grid(
            row=0, column=3, sticky="w"
        )
        self.proxy_host_var = tk.StringVar()
        self.proxy_host_entry = ttk.Entry(
            settings_card, textvariable=self.proxy_host_var, width=18
        )
        self.proxy_host_entry.grid(row=0, column=4, padx=(6, 10))

        ttk.Label(settings_card, text=self.t("port")).grid(row=0, column=5, sticky="w")
        self.proxy_port_var = tk.StringVar()
        self.proxy_port_entry = ttk.Entry(
            settings_card, textvariable=self.proxy_port_var, width=8
        )
        self.proxy_port_entry.grid(row=0, column=6, padx=(6, 10))

        self.save_settings_button = ttk.Button(
            settings_card,
            text=self.t("save_apply"),
            style="Accent.TButton",
            command=self.on_save_settings,
        )
        self.save_settings_button.grid(row=0, column=7, sticky="e")

        ttk.Label(
            settings_card,
            text=self.t("port_note"),
            style="Sub.TLabel",
            wraplength=860,
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))

        # Log card ----------------------------------------------------------
        log_card = ttk.LabelFrame(
            root, text=self.t("log_card"), style="Card.TLabelframe"
        )
        log_card.grid(row=5, column=0, sticky="nsew", padx=18, pady=(4, 8))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_card,
            height=10,
            wrap="word",
            relief="flat",
            bd=0,
            font=self.font_mono,
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_card, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(root, padding=(18, 0, 18, 12))
        footer.grid(row=6, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)

        self.refresh_button = ttk.Button(
            footer, text=self.t("refresh"), command=self.refresh_status
        )
        self.refresh_button.grid(row=0, column=0, sticky="w")

        ttk.Label(
            footer,
            text=self.t("footer_note"),
            style="Sub.TLabel",
            wraplength=720,
        ).grid(row=0, column=1, sticky="e")

        self._interactive_widgets = [
            self.provider_combo,
            self.toggle_button,
            self.autostart_check,
            self.route_var,
            self.egress_var,
            self.listen_port_entry,
            self.auto_port_button,
            self.proxy_host_entry,
            self.proxy_port_entry,
            self.save_settings_button,
            self.refresh_button,
            self.menu_button,
        ]
        self._log(f"{APP_NAME} {APP_VERSION}")
        self._log(f"backend: {self.backend_dir}")
        self._log(f"node   : {self.node or '(not found)'}")

    # ------------------------------------------------------------------ theme
    def _apply_palette(self) -> None:
        p = self.palette
        enabled = bool(self.status and self.status.get("state", {}).get("enabled"))
        self.root.configure(bg=p.bg)
        self.phase_label.configure(bg=p.green if enabled else p.muted, fg="white")
        self.route_label.configure(foreground=p.text)
        self.toggle_button.configure(
            bg=p.red if enabled else p.accent,
            fg="white",
            activebackground=(
                "#b8403c" if enabled and self.dark else "#e06b66"
                if enabled
                else p.accent_hover
            ),
            activeforeground="white",
            disabledforeground="#dddddd",
        )
        self.log_text.configure(
            bg=p.log_bg,
            fg=p.text,
            insertbackground=p.text,
            selectbackground=p.accent,
        )
        for label in self.value_labels.values():
            label.configure(foreground=p.text)

    def _apply_theme(self, refresh: bool = True) -> None:
        self.dark = self._effective_dark()
        self.palette = Palette(self.dark)
        if sv_ttk is not None:
            sv_ttk.set_theme("dark" if self.dark else "light")
        self._apply_palette()
        if refresh and self.status is not None:
            self.refresh_status()

    def _poll_system_theme(self) -> None:
        try:
            current = self._system_is_dark()
            if self.theme_mode == "system" and current != self._last_system_dark:
                self._last_system_dark = current
                self._apply_theme(refresh=False)
            self.root.after(5000, self._poll_system_theme)
        except Exception:
            pass

    # ------------------------------------------------------------------ utils
    def _log(self, text: str) -> None:
        if not text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 800:
            self.log_text.delete("1.0", f"{lines - 700}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in self._interactive_widgets:
            try:
                if isinstance(widget, tk.StringVar):
                    continue
                widget.configure(state=state)
            except tk.TclError:
                pass
        if not busy:
            self.provider_combo.configure(state="readonly")
        self.root.configure(cursor="watch" if busy else "")

    def _run_manage(self, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
        if not self.node:
            raise RuntimeError("Node.js runtime not found (runtime/node.exe or PATH)")
        if not self.manage.is_file():
            raise RuntimeError(f"backend/manage.js not found at {self.manage}")
        with tempfile.TemporaryDirectory(prefix="callidfix-gui-") as tmp:
            out_path = Path(tmp) / "out.txt"
            err_path = Path(tmp) / "err.txt"
            with open(out_path, "wb") as out_file, open(err_path, "wb") as err_file:
                proc = subprocess.run(
                    [self.node, str(self.manage), *args],
                    cwd=str(self.backend_dir),
                    env=self.env,
                    stdin=subprocess.DEVNULL,
                    stdout=out_file,
                    stderr=err_file,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=timeout,
                )
            stdout = out_path.read_bytes().decode("utf-8", errors="replace")
            stderr = err_path.read_bytes().decode("utf-8", errors="replace")
        return proc.returncode, stdout, stderr

    def _run_sequence_async(
        self, title: str, commands: list[list[str]], timeout: int = 180
    ) -> None:
        if self.busy or not commands:
            return
        self._set_busy(True)
        self._log(f"\n> {title}")

        def worker() -> None:
            results: list[tuple[list[str], int, str, str]] = []
            for command in commands:
                try:
                    code, out, err = self._run_manage(command, timeout=timeout)
                except Exception as exc:  # noqa: BLE001
                    code, out, err = 1, "", str(exc)
                results.append((command, code, out, err))
                if code != 0:
                    break
            self.work_queue.put(("commands", results))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_work_queue)

    def _poll_work_queue(self) -> None:
        try:
            kind, payload = self.work_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_work_queue)
            return
        if kind == "commands":
            failed = None
            for command, code, out, err in payload:
                self._log(f"$ manage.js {' '.join(command)}")
                if out.strip():
                    self._log(out.strip())
                if err.strip():
                    self._log(err.strip())
                if code != 0:
                    failed = (command, code, err or out)
            self._set_busy(False)
            if failed:
                command, code, message = failed
                self._log(f"! command failed ({code}): {' '.join(command)}")
                lowered = message.lower()
                if (
                    ("eperm" in lowered or "operation not permitted" in lowered)
                    and "config.toml" in lowered
                ):
                    text = self.t(
                        "sandbox_write_denied",
                        message=message.strip()[:1200],
                    )
                else:
                    text = self.t(
                        "command_failed",
                        command=" ".join(command),
                        message=message.strip()[:1200],
                    )
                messagebox.showerror(APP_NAME, text, parent=self.root)
            self.refresh_status()
        else:
            self._set_busy(False)

    # --------------------------------------------------------------- refresh
    def refresh_status(self, initial: bool = False) -> None:
        if self.busy and not initial:
            return
        try:
            code, out, err = self._run_manage(["status", "--json"], timeout=25)
            if code != 0:
                raise RuntimeError(err.strip() or out.strip() or "status failed")
            status = json.loads(out.strip())
        except Exception as exc:  # noqa: BLE001
            self._set_busy(False)
            self._log(f"! {self.t('backend_status_failed', error=exc)}")
            if initial:
                messagebox.showerror(
                    APP_NAME,
                    self.t("backend_error", error=exc),
                    parent=self.root,
                )
            return

        self.status = status
        provider_info = status.get("provider", {})
        state = status.get("state", {})
        egress = status.get("egress", {})
        env = status.get("env", {})
        enabled = bool(state.get("enabled"))
        active = provider_info.get("active")
        mode = egress.get("mode", "proxy")

        # Provider combobox
        self._suppress_provider_event = True
        display_to_id: dict[str, str | None] = {self.t("openai_builtin"): None}
        values = [self.t("openai_builtin")]
        for provider in provider_info.get("providers", []):
            pid = provider.get("id")
            if not pid:
                continue
            display = f"{pid}  —  {provider.get('name') or pid}"
            if display in display_to_id:
                display = f"{pid}  —  {provider.get('baseUrl') or ''}"
            display_to_id[display] = pid
            values.append(display)
        if active and not any(value == active for value in display_to_id.values()):
            display = f"{active}  —  (missing section)"
            display_to_id[display] = active
            values.append(display)
        self._provider_display = display_to_id
        self.provider_combo.configure(values=values)
        current_display = self.t("openai_builtin")
        for display, pid in display_to_id.items():
            if pid == active:
                current_display = display
                break
        self.provider_combo.set(current_display)
        self._suppress_provider_event = False

        # Provider note
        model = provider_info.get("model")
        catalog = provider_info.get("catalog")
        if active:
            if catalog:
                note = self.t(
                    "provider_note_active", model=model or "?", catalog=catalog
                )
            else:
                note = self.t("provider_note_active_nocatalog", model=model or "?")
        else:
            note = self.t("provider_note_builtin")
            if model:
                note += self.t("provider_note_model", model=model)
            if catalog:
                note += self.t("provider_note_catalog", catalog=catalog)
        self.provider_note.configure(text=note)

        # Status values
        self.phase_label.configure(
            text=self.t("phase_on") if enabled else self.t("phase_off"),
            bg=self.palette.green if enabled else self.palette.muted,
        )
        proxy = status.get("proxy", {})
        if enabled and proxy.get("running"):
            proxy_text = self.t("running", pid=proxy.get("pid"))
        elif enabled:
            proxy_text = self.t("on_not_running")
        elif proxy.get("listenerPid"):
            proxy_text = self.t("port_held", pid=proxy.get("listenerPid"))
        else:
            proxy_text = self.t("stopped")
        listen = status.get("listen", {})
        listen_text = str(listen.get("url", ""))
        if enabled and listen_text:
            listen_text = f"{listen_text} (pid {proxy.get('pid') or '?'})"
        mode_label = {
            "proxy": self.t("egress_proxy"),
            "direct": self.t("egress_direct"),
            "auto": self.t("egress_auto"),
        }.get(mode, str(mode))
        egress_text = mode_label
        if mode != "direct":
            egress_text += f"  →  {egress.get('proxyHost')}:{egress.get('proxyPort')}"
            if egress.get("proxyReachable") is True:
                egress_text += f"  [{self.t('reachable')}]"
            elif egress.get("proxyReachable") is False:
                egress_text += f"  [{self.t('unreachable')}]"
        env_state = env.get("state", "—")
        env_key = {
            "active": "env_active",
            "parked": "env_parked",
            "absent": "env_absent",
            "direct (no proxy lines)": "env_direct",
            "not managed": "env_not_managed",
        }.get(env_state)
        env_text = self.t(env_key) if env_key else env_state
        if env.get("httpProxy"):
            env_text += f"  ({env.get('httpProxy')})"
        autostart_text = self.t("phase_on") if status.get("autostart") else self.t("phase_off")

        self.value_labels["proxy_value"].configure(text=proxy_text)
        self.value_labels["listen_value"].configure(text=listen_text)
        self.value_labels["egress_value"].configure(text=egress_text)
        self.value_labels["env_value"].configure(text=env_text)
        self.value_labels["autostart_value"].configure(text=autostart_text)

        route = "direct"
        if enabled:
            route = "fix"
        elif mode != "direct":
            route = "upstream"
        self.route_var.set(route)
        self.egress_var.set(mode if mode in {"proxy", "direct", "auto"} else "proxy")
        if enabled:
            route_text = self.t(
                "route_fix", port=listen.get("port"), egress=mode_label
            )
            if active is None:
                route_text += self.t("route_openai_suffix")
        elif mode == "direct":
            route_text = self.t("route_direct")
        else:
            route_text = self.t(
                "route_upstream",
                host=egress.get("proxyHost"),
                port=egress.get("proxyPort"),
            )
        self.route_label.configure(text=route_text)

        self.toggle_button.configure(
            text=self.t("stop_proxy") if enabled else self.t("start_proxy"),
            bg=self.palette.red if enabled else self.palette.accent,
        )

        self._suppress_autostart_event = True
        self.autostart_var.set(bool(status.get("autostart")))
        self._suppress_autostart_event = False

        # Config values
        config_path = status.get("paths", {}).get("configFile")
        if config_path:
            self.config_path = Path(config_path)
        try:
            self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            self.config = None
        if self.config:
            self._suppress_setting_events = True
            self.listen_port_var.set(str(self.config.get("listenPort", "")))
            egress_cfg = self.config.get("egress", {})
            self.proxy_host_var.set(
                str(egress_cfg.get("proxyHost") or egress_cfg.get("clashHost") or "")
            )
            self.proxy_port_var.set(
                str(egress_cfg.get("proxyPort") or egress_cfg.get("clashPort") or "")
            )
            self._suppress_setting_events = False

        for warning in status.get("warnings") or []:
            self._log(f"! {self.t('warning_prefix')}: {warning}")

    # ---------------------------------------------------------------- actions
    def on_provider_changed(self, _event=None) -> None:
        if self._suppress_provider_event or self.busy or not self.status:
            return
        display = self.provider_combo.get()
        target = self._provider_display.get(display)
        current = self.status.get("provider", {}).get("active")
        if target == current:
            return
        commands = [["provider", "use", target or "openai"]]
        if self.status.get("state", {}).get("enabled"):
            commands.append(["route", "fix"])
        self._run_sequence_async(
            self.t(
                "action_switch_provider",
                target=target or self.t("openai_builtin"),
            ),
            commands,
        )
        self._log(self.t("provider_switch_note"))

    def on_autostart_changed(self) -> None:
        if self._suppress_autostart_event or self.busy:
            return
        want = bool(self.autostart_var.get())
        self._run_sequence_async(
            self.t("action_autostart_on" if want else "action_autostart_off"),
            [["autostart", "on" if want else "off"]],
        )

    def on_toggle_proxy(self) -> None:
        if self.busy or not self.status:
            return
        enabled = bool(self.status.get("state", {}).get("enabled"))
        if enabled:
            self._run_sequence_async(self.t("action_stop_proxy"), [["off"]])
        else:
            self._run_sequence_async(self.t("action_start_proxy"), [["route", "fix"]])

    def on_route_changed(self, route: str) -> None:
        if self.busy or not self.status:
            return
        current = "direct"
        if self.status.get("state", {}).get("enabled"):
            current = "fix"
        elif self.status.get("egress", {}).get("mode") != "direct":
            current = "upstream"
        if route == current:
            return
        command = {
            "fix": ["route", "fix"],
            "upstream": ["route", "upstream"],
            "direct": ["route", "direct"],
        }[route]
        label = {
            "fix": self.t("route_fix_short"),
            "upstream": self.t("route_upstream_short"),
            "direct": self.t("route_direct_short"),
        }[route]
        self._run_sequence_async(self.t("action_route", route=label), [command])

    def on_egress_changed(self, mode: str) -> None:
        if self.busy or not self.status:
            return
        if mode == self.status.get("egress", {}).get("mode"):
            return
        self._run_sequence_async(
            self.t("action_egress", mode=mode), [["egress", mode]]
        )

    def on_save_settings(self) -> None:
        if self.busy:
            return
        try:
            listen_port = int(self.listen_port_var.get().strip())
            proxy_port = int(self.proxy_port_var.get().strip())
            proxy_host = self.proxy_host_var.get().strip()
        except ValueError:
            messagebox.showerror(
                APP_NAME, self.t("invalid_port_digits"), parent=self.root
            )
            return
        if not (1 <= listen_port <= 65535 and 1 <= proxy_port <= 65535):
            messagebox.showerror(
                APP_NAME, self.t("invalid_port_range"), parent=self.root
            )
            return
        if not proxy_host:
            messagebox.showerror(
                APP_NAME, self.t("empty_proxy_host"), parent=self.root
            )
            return
        if not self.config_path.exists():
            messagebox.showerror(
                APP_NAME,
                self.t("config_not_found", path=self.config_path),
                parent=self.root,
            )
            return
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME,
                self.t("config_read_failed", error=exc),
                parent=self.root,
            )
            return

        config["listenHost"] = config.get("listenHost", "127.0.0.1")
        config["listenPort"] = listen_port
        egress = config.get("egress") if isinstance(config.get("egress"), dict) else {}
        egress["proxyHost"] = proxy_host
        egress["proxyPort"] = proxy_port
        if str(egress.get("mode", "")).lower() == "clash":
            egress["mode"] = "proxy"
        egress.setdefault("mode", "proxy")
        config["egress"] = egress
        try:
            self.config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME,
                self.t("config_write_failed", error=exc),
                parent=self.root,
            )
            return

        enabled = bool(self.status and self.status.get("state", {}).get("enabled"))
        command = ["route", "fix"] if enabled else ["off"]
        self._run_sequence_async(self.t("action_save_ports"), [command])

    def pick_free_port(self) -> None:
        try:
            host = (self.config or {}).get("listenHost", "127.0.0.1")
            self.listen_port_var.set(str(find_free_port(host)))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME, self.t("free_port_failed", error=exc), parent=self.root
            )

    # ------------------------------------------------------------------- misc
    def open_data_folder(self) -> None:
        try:
            os.startfile(str(self.data_dir))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME, self.t("open_folder_failed", error=exc), parent=self.root
            )

    def trust_sign(self) -> None:
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                APP_NAME, self.t("trust_sign_unavailable"), parent=self.root
            )
            return
        candidates = [
            self.base_dir / "trust-sign.ps1",
            self.base_dir / "packaging" / "trust-sign.ps1",
            self.base_dir.parent / "trust-sign.ps1",
            self.base_dir.parent / "packaging" / "trust-sign.ps1",
        ]
        script = next((path for path in candidates if path.is_file()), candidates[0])
        if not script.is_file():
            messagebox.showerror(
                APP_NAME,
                self.t("trust_sign_missing", path=str(script)),
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            APP_NAME, self.t("trust_sign_confirm"), parent=self.root
        ):
            return
        try:
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-AppPath",
                    sys.executable,
                    "-Relaunch",
                ],
                cwd=str(self.base_dir),
                creationflags=CREATE_NEW_CONSOLE,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME, self.t("trust_sign_failed", error=exc), parent=self.root
            )
            return
        # The helper waits for this process to exit, signs the EXE, then relaunches it.
        self.root.after(300, self.root.destroy)

    def open_readme(self) -> None:
        readme = resolve_readme(self.base_dir, self.lang)
        if not readme:
            messagebox.showinfo(APP_NAME, self.t("readme_missing"), parent=self.root)
            return
        try:
            os.startfile(str(readme))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME, self.t("readme_open_failed", error=exc), parent=self.root
            )

    def show_about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            self.t("about_text", name=APP_NAME, version=APP_VERSION),
            parent=self.root,
        )


class SettingsDialog:
    def __init__(self, app: App) -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title(app.t("settings_title"))
        self.window.transient(app.root)
        self.window.resizable(False, False)
        self.window.geometry("620x420")
        try:
            self.window.grab_set()
        except Exception:
            pass
        try:
            icon = resolve_asset(app.base_dir, "app.ico")
            if icon.is_file():
                self.window.iconbitmap(str(icon))
        except Exception:
            pass
        self._build()

    def _build(self) -> None:
        app = self.app
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=app.t("settings_language")).grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.lang_combo = ttk.Combobox(
            frame,
            state="readonly",
            values=list(LANG_LABELS.values()),
            width=28,
        )
        self.lang_combo.set(LANG_LABELS[app.lang])
        self.lang_combo.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text=app.t("settings_appearance")).grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.theme_combo = ttk.Combobox(
            frame,
            state="readonly",
            values=[
                app.t("theme_system"),
                app.t("theme_light"),
                app.t("theme_dark"),
            ],
            width=28,
        )
        self.theme_combo.set(
            {
                "system": app.t("theme_system"),
                "light": app.t("theme_light"),
                "dark": app.t("theme_dark"),
            }[app.theme_mode]
        )
        self.theme_combo.grid(row=1, column=1, sticky="ew", pady=4)

        families = sorted({name for name in tkfont.families(app.root) if not name.startswith("@")})
        ttk.Label(frame, text=app.t("settings_font_zh")).grid(
            row=2, column=0, sticky="w", pady=4
        )
        self.font_zh_combo = ttk.Combobox(
            frame, state="readonly", values=families, width=28
        )
        self.font_zh_combo.set(app.font_zh)
        self.font_zh_combo.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text=app.t("settings_font_en")).grid(
            row=3, column=0, sticky="w", pady=4
        )
        self.font_en_combo = ttk.Combobox(
            frame, state="readonly", values=families, width=28
        )
        self.font_en_combo.set(app.font_en)
        self.font_en_combo.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text=app.t("settings_font_size")).grid(
            row=4, column=0, sticky="w", pady=4
        )
        self.size_var = tk.StringVar(value=str(app.font_size))
        ttk.Spinbox(
            frame, from_=8, to=22, textvariable=self.size_var, width=8
        ).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(
            frame,
            text=app.t("settings_note"),
            wraplength=500,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 8))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text=app.t("cancel"), command=self.window.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(
            buttons,
            text=app.t("save"),
            style="Accent.TButton",
            command=self.save,
        ).pack(side="right")

    def save(self) -> None:
        app = self.app
        lang = LANG_BY_LABEL.get(self.lang_combo.get(), app.lang)
        theme = {
            app.t("theme_system"): "system",
            app.t("theme_light"): "light",
            app.t("theme_dark"): "dark",
        }.get(self.theme_combo.get(), app.theme_mode)
        font_zh = self.font_zh_combo.get() or app.font_zh
        font_en = self.font_en_combo.get() or app.font_en
        try:
            size = int(self.size_var.get())
        except ValueError:
            size = app.font_size
        size = max(8, min(22, size))
        self.window.destroy()
        app.apply_settings(
            {
                "lang": lang,
                "theme": theme,
                "font_zh": font_zh,
                "font_en": font_en,
                "font_size": size,
            }
        )


def main() -> None:
    root = tk.Tk()
    try:
        icon_ico = resolve_asset(app_dir(), "app.ico")
        if icon_ico.is_file():
            root.iconbitmap(str(icon_ico))
    except Exception:
        pass
    try:
        icon_png = resolve_asset(app_dir(), "app.png")
        if icon_png.is_file():
            photo = tk.PhotoImage(file=str(icon_png))
            root.iconphoto(True, photo)
            root._app_icon = photo  # type: ignore[attr-defined]
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
