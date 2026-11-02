# Codex Call ID Fix

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md)

一个本地修复代理 + Windows 小工具，用于处理 Codex Desktop 的报错：

```text
Invalid 'call_id': call_id is required for function_call_output.
```

Codex 有时会把子线程的 app 工具委派（`create_thread` / `send_message_to_thread`）写成没有 `call_id` 的 `function_call_output`。严格的 OpenAI-compatible Responses 接口会拒绝这种请求。代理会在转发前把这些合成条目改写成普通 `user` 消息，让 provider 收到合法 payload。

工具不绑定具体厂商：`config.toml` 里任意 `[model_providers.*]` 都可以接入；监听端口和上游代理端口都是配置项，不写死。

## 功能

- 修复 Responses 请求中缺少 `call_id` 的 `function_call_output`。
- 一个本地代理通过 `/_p/<provider>/...` 路径服务多个 provider。
- 不用手改 `config.toml` 就能开关代理。
- 在 GUI 中切换 Codex 当前供应商，包括 `OpenAI（内置）`（删除 `model_provider`）。
- 三种出站方式：
  - `proxy`：经上游 HTTP 代理（CONNECT）。
  - `direct`：直连 provider。
  - `auto`：先试上游代理，失败后直连。
- 同时管理 `~/.codex/.env`，所以代理关闭后 Codex 也遵循同一出口选择。
- 可选 Windows 登录自启动（隐藏窗口，不需要管理员）。
- CLI + Tkinter GUI。
- 浅色、深色、跟随系统三种外观。
- 简体中文、繁體中文、English 三种界面；中文和英文字体可分别选择，并可调字号。
- 端口可在 GUI / `callidfix.config.json` 中修改。

## 安装（Windows）

下载并运行：

```text
CodexCallIdFix-Setup-1.0.0.exe
```

安装到当前用户目录 `%LOCALAPPDATA%\Programs\CodexCallIdFix`，不需要管理员权限；安装包自带 Node 运行时、README、LICENSE、AUTHORS 和本地签名工具。安装后会运行自检，通过后自动删除安装包。

不想安装时，可以解压 `CodexCallIdFix-1.0.0-portable.zip`，运行里面的 `CodexCallIdFix.exe`。便携包包含 `backend/`、`runtime/node.exe`、文档和签名工具。单独一个 `CodexCallIdFix.exe` 不是完整发行包：它需要同级或上一级目录有 `backend/`，并且有可用的 Node（便携 `runtime/node.exe` 或 PATH 里的 `node`）。

安装完成后：

1. 打开 **Codex Call ID Fix**。
2. 在 **Codex 模型供应商** 中选择供应商。
3. 选择 **Codex 出口**：
   - `修复代理（本地端口）`：Codex 经本代理。
   - `上游代理`：Codex 直接走上游 HTTP 代理，代理关闭。
   - `直接出站`：Codex 直连，代理关闭。
4. 使用修复代理时，选择 **修复代理出站**：
   `上游代理` / `直连` / `自动回退`。
5. 在设置卡片中修改本地监听端口、上游代理地址和端口，会写入 `backend/callidfix.config.json`。
6. 修改 `config.toml`、`.env` 或供应商后，**完全退出并重启 Codex Desktop**。

端口默认值只是示例（本地 7891、上游 7890），可以随时在 GUI 里改。

界面偏好放在 **菜单 → 设置…**（二级菜单），不占主界面：

- 语言：`简体中文` / `繁體中文` / `English`。
- 外观：`跟随系统` / `浅色` / `深色`；跟随系统会读取 Windows 个性化设置并定期刷新。
- 中文字体、英文字体分别选择，另可调字号。中文界面用中文字体，English 界面用英文字体。

设置保存在 `backend/gui.json`（运行时生成）。

## 备份与卸载

每次安装/升级都会在复制新文件前自动创建备份：

```text
%LOCALAPPDATA%\CodexCallIdFix\backups\<时间戳>-v1.0.0\
  manifest.json
  codex\config.toml        （安装时存在才复制）
  codex\.env               （安装时存在才复制）
  install\backend\...      （升级时备份旧的 config/state/gui）
```

实际备份根目录也会写入安装目录的 `backup-root.txt`。这个快照用于**手动灾难恢复**；卸载时不会拿它整体覆盖 `config.toml`，以免抹掉你安装后做的修改。

卸载（`uninstall.cmd`，如果注册表项创建成功也可从 Windows“应用和功能”卸载）按顺序执行：

1. `manage.js off`：还原工具改过的 `base_url`，按当前 egress 恢复/停放 `.env`，停止代理。
2. `manage.js autostart off`：删除登录自启动项。
3. 删除卸载注册表项、Run 值和开始菜单/桌面快捷方式。
4. 删除安装目录。
5. **只有第 1 步成功后才删除备份根目录**。

如果第 1 步失败（例如 provider 的原始 URL 未知），卸载会弹窗提示，保留安装目录和备份，不会强行删除。先修复 `fallbackOriginalBaseUrls` 或对应的 provider 段，再运行 `uninstall.cmd`。

## 在另一台电脑上测试

当前这台构建机没有复现 `create_thread` / `send_message_to_thread` 的 bug。本机 Codex Desktop、Codex CLI、Windows、Node、Python 版本记录在 [`docs/environment.md`](docs/environment.md)。第二台电脑的测试步骤在 [`docs/reproduce.md`](docs/reproduce.md)；测试前先记录新机器的 Codex 版本，不要上传 `.codex` 的认证/状态文件或 API key。

## 工作原理

```text
Codex
  -> http://<listenHost>:<listenPort>/_p/<provider>/<原始路径>
  -> codex-callid-fix（改写 body）
  -> 上游 HTTP 代理  或  直接 TCP/TLS
  -> provider 原始 base_url
```

`on` 会把 provider 的 `base_url`：

```toml
[model_providers.MyProvider]
base_url = "https://api.example.com/v1"
```

改为：

```toml
[model_providers.MyProvider]
base_url = "http://127.0.0.1:7891/_p/MyProvider/v1"
```

`/_p/<provider>/` 前缀让一个监听端口服务多个 provider。`off` 会扫描**所有** `[model_providers.*]`，还原指向本代理的 `base_url`。

原始 URL 维护在两处：

1. `backend/state.json` 的 `originalBaseUrls`（`on` 时记录）；
2. `backend/callidfix.config.json` 的 `fallbackOriginalBaseUrls`（`on` 自动写入，`state.json` 丢失时使用）。

只改 `base_url` 这一行，其他字段、注释、BOM、换行都会保留。如果无法确定原始 URL，`off` 会拒绝停止，避免 Codex 指向一个已经消失的代理。

## 切换供应商

GUI 列出：

- `OpenAI（内置）`：删除顶层 `model_provider`，让 Codex 使用内置 provider；
- `~/.codex/config.toml` 中的每个 `[model_providers.<id>]`。

选择自定义供应商会写入 `model_provider = "<id>"`。它**不会**改 `model` 或 `model_catalog_json`；如果切换后 Codex 报模型不存在，请在 Codex 的模型选择器里选匹配的模型（或自行修改 `model_catalog_json`）。模型名是 provider 相关的，工具不猜测。

默认代理管理**所有**自定义供应商（`"providers": "all"`），所以切换当前供应商不需要重新应用代理。只管理部分供应商时，用显式数组：

```json
"providers": [
  "MyProvider",
  { "id": "AnotherProvider", "egress": "direct" }
]
```

`egress` 可以按 provider 覆盖全局出站方式（只在代理开启时生效）。

## Codex `.env`

出口选择也会管理 `~/.codex/.env`：

- `proxy` / `auto`：确保 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 指向配置的上游代理，并把 `localhost,127.0.0.1,::1` 合并进 `NO_PROXY`。
- `direct`：移除这些代理变量。如果文件只剩代理变量就删除文件，内容保存到 `~/.codex/.env.callidfix-parked`，切回 `proxy` 时恢复。
- 其他变量（例如 API key）保留。
- 第一次修改会创建 `~/.codex/.env.callidfix-backup`。

修改 `.env` 后需要重启 Codex Desktop。

如果你的代理客户端还设置了 **Windows 系统代理**，只删 `.env` 不一定能强制 Codex 直连；需要在客户端里关闭系统代理。修复代理自己的 `direct` 模式使用原始 TCP/TLS，不受系统代理影响。

## 自启动

在 GUI 勾选 **登录 Windows 时自动启动（隐藏窗口）**，或：

```powershell
node backend/manage.js autostart on
node backend/manage.js autostart status
node backend/manage.js autostart off
```

会写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `codex-callid-fix` 值。登录时 `start-hidden.vbs` 执行 `manage.js boot`，按上次开关状态恢复：上次是 ON 就启动代理并修复 `config.toml`/`.env`；上次是 OFF 就停止残留进程并保持直连配置。不需要管理员权限。

## CLI

GUI 只是同一套 CLI 的前端：

```text
node manage.js on
node manage.js off
node manage.js toggle
node manage.js status [--json]
node manage.js restart
node manage.js route fix [proxy|direct|auto]
node manage.js route upstream
node manage.js route direct
node manage.js egress <proxy|direct|auto>
node manage.js provider list [--json]
node manage.js provider use <id|openai>
node manage.js autostart <on|off|status>
node manage.js boot
```

示例：

```powershell
# 所有自定义 provider 走修复代理，直连出站
node backend/manage.js route fix direct

# 关闭代理，Codex 直接走上游代理
node backend/manage.js route upstream

# 关闭代理，Codex 直连
node backend/manage.js route direct

# 切换到内置 OpenAI
node backend/manage.js provider use openai
```

健康检查：

```powershell
curl.exe http://127.0.0.1:7891/__callidfix/health
```

## 配置

`backend/callidfix.config.json`：

```json
{
  "listenHost": "127.0.0.1",
  "listenPort": 7891,
  "providers": "all",
  "fallbackOriginalBaseUrls": {},
  "egress": {
    "mode": "proxy",
    "proxyHost": "127.0.0.1",
    "proxyPort": 7890,
    "connectTimeoutMs": 15000,
    "autoProbeMs": 3000
  },
  "codexEnv": {
    "manage": true,
    "noProxy": "localhost,127.0.0.1,::1"
  }
}
```

- `listenPort`：本地修复代理端口；在 GUI 或这里改，`on`/`restart` 会重新绑定并改写 `base_url`。
- `egress.proxyHost` / `proxyPort`：上游 HTTP 代理，端口任意，代理逻辑没有写死。
- `egress.mode`：`proxy`、`direct`、`auto`。
- `providers`：`"all"` 或显式数组。
- `fallbackOriginalBaseUrls`：`on` 自动填充，也可手工编辑用于恢复。
- `codexEnv.manage`：设为 `false` 可禁止工具修改 `~/.codex/.env`。

## 本地自签名（仅本机）

安装包自带：

```text
trust-sign.cmd
trust-sign.ps1
```

安装后可以运行 **开始菜单 → Trust & Sign Codex Call ID Fix**，或 GUI 菜单 **菜单 → 本地信任并签名…**。它会：

1. 在 `Cert:\CurrentUser\My` 创建自签名代码签名证书
   （`CN=Hungry-M (Codex Call ID Fix)`）；
2. 把公钥证书加入 `CurrentUser\Root` 和 `CurrentUser\TrustedPublisher`；
3. 等待 GUI 关闭，用 SHA-256 给 `CodexCallIdFix.exe` 签名，然后重新打开。

这能消除本机的“未知发布者”状态，也可用于本地应用控制策略；**不会**让其他电脑信任，SmartScreen 的信誉判断也可能仍然生效。只在自己控制的机器上使用。删除本地证书：

```powershell
trust-sign.cmd -RemoveCert
```

`-RemoveCert` 使用 `certutil -user -delstore`，因为 PowerShell 不允许直接删除当前用户 Root 存储项。

## 从源码构建

要求：Windows 10/11、Python 3.10+、PyInstaller、`sv-ttk`、Node.js（开发运行和打包 Node 运行时用）。

```powershell
python -m pip install pyinstaller sv-ttk
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1
```

输出：

```text
dist/CodexCallIdFix.exe
dist/CodexCallIdFix-Setup-1.0.0.exe
dist/SHA256SUMS.txt
```

开发运行：

```powershell
python gui/app.py
node backend/manage.js status
```

安装包内置 GUI exe、`backend/`、便携 `node.exe`、图标、README、LICENSE、AUTHORS。卸载程序写入安装目录，并在 Windows“应用和功能”注册（当前用户）。

GitHub Actions（`.github/workflows/build.yml`）会在 push 时构建，推送 `v*` tag 时把 EXE/校验和附加到 Release。

## 作者与代码签名

作者是 **Hungry-M**（<https://github.com/Hungry-M>）。作者信息在 `AUTHORS.md`、PyInstaller 版本资源、安装包 `Publisher` 和 `LICENSE` 中。二进制和包元数据不写邮箱；GitHub 提交和开源元数据用 `noreply` 没问题。

发布二进制默认**没有签名**。未签名可以运行，但 SmartScreen 会显示“未知发布者”。正式签名需要 OV/EV 代码签名证书；CA 需要核验真实身份/联系方式，`noreply` 不能用于证书本身。签名脚本是 `packaging/sign.ps1`，CI 可配置 `CODESIGN_PFX_BASE64`、`CODESIGN_PFX_PASSWORD` 自动签名。

## 目录

```text
backend/
  manage.js              CLI：config.toml/.env/供应商/自启动管理
  server.js              本地修复代理
  start-hidden.vbs       隐藏登录入口
  callidfix.config.json  用户配置
gui/app.py               Tkinter GUI（sv-ttk 主题）
packaging/
  installer.py           自删除的当前用户安装器
  build.ps1              一键发布构建
  sign.ps1               可选正式签名
  trust-sign.ps1/.cmd    本地自签名工具
assets/app.ico           应用/安装包图标
.github/workflows/       CI 构建 + 可选签名 + Release
AUTHORS.md               作者信息
LICENSE                  MIT
stop.cmd                 CLI 快捷方式（off）
```

运行时在 `backend/` 生成：`state.json`、`server.log`、`node-path.txt`、`gui.json`。安装根目录还有 `backup-root.txt`；安装前快照在 `%LOCALAPPDATA%\CodexCallIdFix\backups\`。

## 故障排查

- **Codex 仍报旧错误**：完全退出 Codex Desktop（不是只关窗口）再启动，让它重新读取 `config.toml` 和 `.env`。
- **上游代理不可达**：状态卡会显示 `[不可达]`；改用 `自动回退` 或 `直连`，或修正地址/端口。
- **本地端口被占用**：在 GUI 改本地端口；`on` 会停止记录的旧实例并重新绑定。
- **`off` 拒绝停止**：某个 provider 指向代理但原始 URL 未知。补到 `fallbackOriginalBaseUrls`，再运行 `off`。
- **切换 OpenAI 后模型报错**：`model` / `model_catalog_json` 仍指向上一个 provider。在 Codex 选择 OpenAI 模型，或修改这些键。
- **`EPERM ... config.toml...tmp`**：当前进程运行在受限令牌下（例如 Codex 的 Windows 沙箱），对 `~/.codex` 只有读权限。请从开始菜单或资源管理器启动 GUI，不要从 Codex 终端启动；`manage.js provider use` 同理。
- **在 Codex 沙箱外运行**：从受限 Codex 终端写 `~/.codex` 可能被拒绝；用 GUI 或普通 PowerShell。
- **安装器提示快捷方式/卸载注册表失败**：某些加固环境会拒绝未签名 EXE 写注册表或快捷方式。应用仍会安装并自检；用安装目录的 `uninstall.cmd` 卸载，桌面快捷方式没创建时用开始菜单快捷方式。
- **“backend/manage.js not found”**：单独一个 `CodexCallIdFix.exe` 没有后端。请用安装包，或解压 `CodexCallIdFix-1.0.0-portable.zip`；从源码目录运行时，把 `backend/` 放在 EXE 同级或上一级，并提供 `runtime/node.exe` 或 PATH 中的 Node。
- **“Could not create temporary directory”**：onefile 启动器现在解压到 EXE 旁边（`--runtime-tmpdir "."`）。请从可写目录运行（安装目录 / Downloads / 桌面），不要从 `Program Files` 或只读网络共享运行。开始菜单快捷方式已设置工作目录。
- **SmartScreen 显示“未知发布者”**：发布二进制默认未签名；正式签名见上面的“作者与代码签名”，或在本机使用 `Trust & Sign`。
- **Windows“应用和功能”里没有条目**：用安装目录的 `uninstall.cmd`；它也会先执行 `manage.js off` 和 `autostart off` 再删除文件。
- 日志：`backend/server.log`（5 MB 轮转）。

## 范围与免责声明

这是针对 Codex Desktop 序列化 bug 的本地 workaround，不是 OpenAI/Codex 官方组件。默认只监听 loopback，不会把你的提示词发到已配置 provider `base_url` 以外的地方。
