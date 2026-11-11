# Codex Call ID Fix

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md)

一個本機修復代理 + Windows 小工具，用於處理 Codex Desktop 的錯誤：

```text
Invalid 'call_id': call_id is required for function_call_output.
```

Codex 有時會把子執行緒的 app 工具委派（`create_thread` / `send_message_to_thread`）寫成沒有 `call_id` 的 `function_call_output`。嚴格的 OpenAI-compatible Responses 介面會拒絕這種請求。代理會在轉送前把這些合成項目改寫成一般 `user` 訊息，讓供應商收到合法 payload。

工具不綁定特定廠商：`config.toml` 裡任何 `[model_providers.*]` 都可以接入；監聽連接埠和上游代理連接埠都是設定值，不是寫死的。

> **狀態：0.1.6 相容 shim。** 2026-11-11 在原供應商恢復額度後重現了原始故障；開啟修復代理後問題消失。這是該環境下的已確認 workaround，不是通用的 Codex 修復；請結合 `backend/server.log` 裡的 `rewrote=` 和你的供應商/版本驗證。
>
> 本專案是獨立專案，與 OpenAI 沒有隸屬或背書關係。

## 功能

- 修復 Responses 請求中缺少 `call_id` 的 `function_call_output`。
- 一個本機代理透過 `/_p/<provider>/...` 路徑服務多個供應商。
- 不用手改 `config.toml` 就能開關代理。
- 在 GUI 中切換 Codex 目前供應商，包括 `OpenAI（內建）`（刪除 `model_provider`）。
- 三種出站方式：
  - `proxy`：經上游 HTTP 代理（CONNECT）。
  - `direct`：直連供應商。
  - `auto`：先試上游代理，失敗後直連。
- 同時管理 `~/.codex/.env`，所以代理關閉後 Codex 也遵循同一個出口選擇。
- 可選 Windows 登入自動啟動（隱藏視窗，不需要系統管理員權限）。
- CLI + Tkinter GUI。
- 淺色、深色、跟隨系統三種外觀。
- 簡體中文、繁體中文、English 三種介面；中文和英文字型可分別選擇，並可調整字型大小。
- 連接埠可在 GUI / `callidfix.config.json` 中修改。

## 安裝（Windows）

下載並執行：

```text
CodexCallIdFix-Setup-0.1.6.exe
```

安裝到目前使用者目錄 `%LOCALAPPDATA%\Programs\CodexCallIdFix`，不需要系統管理員權限；安裝套件自帶 Node 執行環境、README、LICENSE、AUTHORS 和本機簽名工具。安裝後會執行自檢，通過後自動刪除安裝套件。

不想安裝時，可以解壓 `CodexCallIdFix-0.1.6-portable.zip`，執行裡面的 `CodexCallIdFix.exe`。可攜包包含 `backend/`、`runtime/node.exe`、文件、簽名工具。單獨一個 `CodexCallIdFix.exe` 不是完整發行包：它需要同級或上一級目錄有 `backend/`，並且有可用的 Node（可攜 `runtime/node.exe` 或 PATH 裡的 `node`）。

安裝完成後：

1. 開啟 **Codex Call ID Fix**。
2. 在 **Codex 模型供應商** 中選擇供應商。
3. 選擇 **Codex 出口**：
   - `修復代理（本機連接埠）`：Codex 經本代理。
   - `上游代理`：Codex 直接走上游 HTTP 代理，代理關閉。
   - `直接出站`：Codex 直連，代理關閉。
4. 使用修復代理時，選擇 **修復代理出站**：
   `上游代理` / `直連` / `自動退回`。
5. 在設定卡片中修改本機監聽連接埠、上游代理位址和連接埠，會寫入 `backend/callidfix.config.json`。
6. 修改 `config.toml`、`.env` 或供應商後，**完全結束並重新啟動 Codex Desktop**。

連接埠預設值只是範例（本機 7891、上游 7890），可以隨時在 GUI 裡修改。

介面偏好放在 **選單 → 設定…**（二級選單），不佔主介面：

- 語言：`简体中文` / `繁體中文` / `English`。
- 外觀：`跟隨系統` / `淺色` / `深色`；跟隨系統會讀取 Windows 個人化設定並定期重新整理。
- 中文字型、英文字型分別選擇，另可調整字型大小。中文介面使用中文字型，English 介面使用英文字型。

設定儲存在 `backend/gui.json`（執行時產生）。

## 備份與解除安裝

每次安裝/升級都會在複製新檔案前自動建立備份：

```text
%LOCALAPPDATA%\CodexCallIdFix\backups\<時間戳>-v0.1.6\
  manifest.json
  codex\config.toml        （安裝時存在才複製）
  codex\.env               （安裝時存在才複製）
  install\backend\...      （升級時備份舊的 config/state/gui）
```

實際備份根目錄也會寫入安裝目錄的 `backup-root.txt`。這個快照用於**手動災難還原**；解除安裝時不會拿它整體覆蓋 `config.toml`，以免抹掉你安裝後做的修改。

可攜版沒有安裝器式的時間戳備份。`manage.js` 第一次修改 `config.toml` 前會建立一次不可覆蓋的快照：

```text
~/.codex/config.toml.callidfix-backup
~/.codex/config.toml.callidfix-backup.json
```

後續切換供應商/路線不會覆蓋它；需要新快照時請明確刪除舊檔案。

解除安裝（`uninstall.cmd`，如果登錄檔項目建立成功也可從 Windows「應用程式與功能」解除安裝）依序執行：

1. `manage.js off`：還原工具改過的 `base_url`，依目前 egress 還原/停放 `.env`，停止代理。
2. `manage.js autostart off`：刪除登入自動啟動項目。
3. 刪除專案子憑證；如果 `CN=Hungry-M` 根下還有其他專案子憑證則保留根。
4. 刪除解除安裝登錄檔項目、Run 值和開始選單/桌面捷徑。
5. 刪除安裝目錄。
6. **只有第 1 步成功後才刪除備份根目錄**。

### 可攜版清理

Portable ZIP 也包含 `cleanup.cmd` / `cleanup.ps1`。它會還原工具改過的 Codex 設定、關閉自動啟動、刪除專案子憑證、刪除符合的 Run/解除安裝登錄檔項目，以及 target 指向該目錄的捷徑；可選擇刪除備份。它不會掃描或刪除無關的 Programs 目錄。

```powershell
cleanup.cmd -Yes
cleanup.cmd -Yes -KeepBackups
cleanup.cmd -Yes -RemoveFolder
cleanup.cmd -Yes -RemoveRoot
```

`-RemoveFolder` 會在指令碼結束後排程刪除 portable 目錄；不加則保留目錄。

`-RemoveRoot` 會刪除 `CN=Hungry-M` 根以及它簽發的**所有**子憑證，包括其他專案；只應在測試機或明確要清除本機根時使用。不加時，如果根下還有其他專案子憑證，cleanup 會保留根。

如果第 1 步失敗（例如供應商的原始 URL 未知），解除安裝會顯示警告，保留安裝目錄和備份，不會強行刪除。先修正 `fallbackOriginalBaseUrls` 或對應的供應商區段，再執行 `uninstall.cmd`。

## 在另一台電腦上測試

2026-11-11 在原供應商恢復額度後重現了原始故障，開啟修復代理後解決。版本記錄見 [`docs/environment.md`](docs/environment.md)，重現記錄方法見 [`docs/reproduce.md`](docs/reproduce.md)，驗證記錄見 [`docs/verification-0.1.6.md`](docs/verification-0.1.6.md)。不要把 `.codex` 的認證/狀態檔案或 API key 上傳到 issue。

## 出站方式

**修復代理出站**只在 **Codex 出口 = 修復代理**時生效，它決定修復代理如何連到供應商：

- `上游代理`：修復代理先連到設定的 HTTP 代理（`proxyHost:proxyPort`），送出 `CONNECT <供應商>:443`，再轉送請求。供應商只能透過該代理連線時用這個。
- `直連`：修復代理直接向供應商建立 TCP/TLS，繞過上游代理和 Windows 系統代理。
- `自動退回`：先試上游代理（受 `autoProbeMs` 限制，預設 3 秒）；TCP/CONNECT 失敗才改直連。如果上游代理連線成功、但供應商回傳 HTTP 錯誤，不會自動改直連。

## Provider profile（Desktop 覆蓋）

Codex 0.134+ 已移除頂層 `profile = "<name>"` 和 `[profiles.<name>]` 表。profile 現在是獨立檔案：

```text
~/.codex/<name>.config.toml
```

CLI 用 `codex --profile <name>` 選擇。Codex Desktop 沒有 profile 選擇器，所以本工具讀取 `<provider>.config.toml`，把受管鍵（`model`、`model_provider`、reasoning/verbosity、catalog、approval、approvals_reviewer、review_model、sandbox）覆蓋到主 `config.toml` 頂層。工具不會再寫 legacy `profile`。

首次切換時，會把目前頂層設定快照到 `<目前 provider>.config.toml`（只建立一次，不覆蓋）。目標沒有 profile 時，會清除 `model` 和 `model_catalog_json`，不把上一個 provider 的參數帶過去，並提出警告。

profile 檔案範例（頂層鍵，不帶 `[profiles.*]`）：

```toml
model_provider = "openai"
model = "gpt-5.6-sol"
model_catalog_json = "C:\\Users\\you\\.codex\\model-catalogs\\openai.json"
```

provider 的傳輸欄位仍放在 `config.toml` 的 `[model_providers.<id>]` 中；不要把 model/catalog/approval/sandbox 寫進這個表。CLI profile 模式直接使用 `codex --profile <name>`；Desktop 的覆蓋只是相容橋。

## 運作原理

```text
Codex
  -> http://<listenHost>:<listenPort>/_p/<provider>/<原始路徑>
  -> codex-callid-fix（改寫 body）
  -> 上游 HTTP 代理  或  直接 TCP/TLS
  -> 供應商原始 base_url
```

`on` 會把供應商的 `base_url`：

```toml
[model_providers.MyProvider]
base_url = "https://api.example.com/v1"
```

改為：

```toml
[model_providers.MyProvider]
base_url = "http://127.0.0.1:7891/_p/MyProvider/v1"
```

`/_p/<provider>/` 前綴讓一個監聽連接埠服務多個供應商。`off` 會掃描**所有** `[model_providers.*]`，還原指向本代理的 `base_url`。

原始 URL 維護在兩處：

1. `backend/state.json` 的 `originalBaseUrls`（`on` 時記錄）；
2. `backend/callidfix.config.json` 的 `fallbackOriginalBaseUrls`（`on` 自動寫入，`state.json` 遺失時使用）。

只改 `base_url` 這一行，其他欄位、註解、BOM、換行都會保留。如果無法確定原始 URL，`off` 會拒絕停止，避免 Codex 指向一個已經消失的代理。

## 切換供應商

GUI 列出：

- `OpenAI（內建）`：刪除頂層 `model_provider`，讓 Codex 使用內建供應商；
- `~/.codex/config.toml` 中的每個 `[model_providers.<id>]`。

選擇自訂供應商會寫入 `model_provider = "<id>"`。它**不會**改 `model` 或 `model_catalog_json`；如果切換後 Codex 回報模型不存在，請在 Codex 的模型選擇器中選擇相符的模型（或自行修改 `model_catalog_json`）。模型名稱與供應商相關，工具不猜測。

預設代理管理**所有**自訂供應商（`"providers": "all"`），所以切換目前供應商不需要重新套用代理。只管理部分供應商時，使用明確陣列：

```json
"providers": [
  "MyProvider",
  { "id": "AnotherProvider", "egress": "direct" }
]
```

`egress` 可以按供應商覆蓋全域出站方式（只在代理開啟時生效）。

## Codex `.env`

出口選擇也會管理 `~/.codex/.env`：

- `proxy` / `auto`：確保 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 指向設定的上游代理，並把 `localhost,127.0.0.1,::1` 合併進 `NO_PROXY`。
- `direct`：移除這些代理變數。如果檔案只剩代理變數就刪除檔案，內容儲存到 `~/.codex/.env.callidfix-parked`，切回 `proxy` 時還原。
- 其他變數（例如 API key）保留。
- 第一次修改會建立 `~/.codex/.env.callidfix-backup`。

修改 `.env` 後需要重新啟動 Codex Desktop。

如果你的代理用戶端還設定了 **Windows 系統代理**，只刪 `.env` 不一定能強制 Codex 直連；需要在用戶端裡關閉系統代理。修復代理自己的 `direct` 模式使用原始 TCP/TLS，不受系統代理影響。

## 自動啟動

在 GUI 勾選 **登入 Windows 時自動啟動（隱藏視窗）**，或：

```powershell
node backend/manage.js autostart on
node backend/manage.js autostart status
node backend/manage.js autostart off
```

會寫入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `codex-callid-fix` 值。登入時 `start-hidden.vbs` 執行 `manage.js boot`，依上次開關狀態還原：上次是 ON 就啟動代理並修復 `config.toml`/`.env`；上次是 OFF 就停止殘留程序並保持直連設定。不需要系統管理員權限。

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

範例：

```powershell
# 所有自訂供應商走修復代理，直連出站
node backend/manage.js route fix direct

# 關閉代理，Codex 直接走上游代理
node backend/manage.js route upstream

# 關閉代理，Codex 直連
node backend/manage.js route direct

# 切換到內建 OpenAI
node backend/manage.js provider use openai
```

健康檢查：

```powershell
curl.exe http://127.0.0.1:7891/__callidfix/health
```

## 設定檔

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

- `listenPort`：本機修復代理連接埠；在 GUI 或這裡修改，`on`/`restart` 會重新綁定並改寫 `base_url`。
- `egress.proxyHost` / `proxyPort`：上游 HTTP 代理，連接埠任意，代理邏輯沒有寫死。
- `egress.mode`：`proxy`、`direct`、`auto`。
- `providers`：`"all"` 或明確陣列。
- `fallbackOriginalBaseUrls`：`on` 自動填充，也可手動編輯用於還原。
- `codexEnv.manage`：設為 `false` 可禁止工具修改 `~/.codex/.env`。

## 本機自簽（僅本機）

安裝套件自帶：

```text
trust-sign.cmd
trust-sign.ps1
```

安裝後可以執行 **開始選單 → Trust & Sign Codex Call ID Fix**，或 GUI 選單 **選單 → 本機信任並簽名…**。它會：

1. 建立或重用本機根 CA `CN=Hungry-M`，加入 `CurrentUser\My` 和 `CurrentUser\Root`；
2. 由根簽發專案子憑證 `CN=codex-callid-fix`，加入 `CurrentUser\My` 和 `CurrentUser\TrustedPublisher`；
3. 等待所有同路徑程序結束、EXE 檔案解鎖，用子憑證 SHA-256 簽名；
4. 無論成功或失敗都重新開啟程式；失敗寫入 `%LOCALAPPDATA%\CodexCallIdFix\trust-sign.log`。

根可以在本機其他專案間重用；每個專案使用自己的子憑證。`-RemoveCert` 先刪除 `codex-callid-fix` 子憑證，只有根下沒有其他專案子憑證時才刪除 `CN=Hungry-M` 根；安裝器的解除安裝程式也會呼叫同一清理邏輯。

這會讓檔案由**本機信任的發行者**簽名，File Properties → Digital Signatures 應顯示簽名者；**不會**讓其他電腦信任，SmartScreen 信譽判斷仍可能警告。它只適合本機開發/測試，不要用它讓別人的 A/B 軟體自動互信。刪除憑證：

```powershell
trust-sign.cmd -RemoveCert
```

`-RemoveCert` 使用 `certutil -user -delstore`，因為 PowerShell 不允許直接刪除目前使用者的 Root 存放區項目。若遇到 `NTE_PERM`，通常是從 Codex/DSH 沙箱啟動；請從開始選單或檔案總管啟動後重試。

## 從原始碼建置

需求：Windows 10/11、Python 3.10+、PyInstaller、`sv-ttk`、Node.js（開發執行和打包 Node 執行環境用）。

```powershell
python -m pip install pyinstaller sv-ttk
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1
```

輸出：

```text
dist/CodexCallIdFix.exe
dist/CodexCallIdFix-Setup-0.1.6.exe
dist/SHA256SUMS.txt
```

開發執行：

```powershell
python gui/app.py
node backend/manage.js status
```

安裝套件內建 GUI exe、`backend/`、可攜 `node.exe`、圖示、README、LICENSE、AUTHORS。解除安裝程式寫入安裝目錄，並在 Windows「應用程式與功能」註冊（目前使用者）。

GitHub Actions（`.github/workflows/build.yml`）會在 push 時建置，推送 `v*` tag 時把 EXE/校驗和附加到 Release。

## 作者與程式碼簽章

作者是 **Hungry-M**（<https://github.com/Hungry-M>）。作者資訊在 `AUTHORS.md`、PyInstaller 版本資源、安裝套件 `Publisher` 和 `LICENSE` 中。二進位檔和套件中繼資料不寫電子郵件；GitHub 提交和開源中繼資料用 `noreply` 沒問題。

發佈的二進位檔預設**沒有簽章**。未簽章可以執行，但 SmartScreen 會顯示「未知發行者」。正式簽章需要 OV/EV 程式碼簽章憑證；CA 需要核驗真實身分/聯絡方式，`noreply` 不能用於憑證本身。簽章腳本是 `packaging/sign.ps1`，CI 可設定 `CODESIGN_PFX_BASE64`、`CODESIGN_PFX_PASSWORD` 自動簽章。

## 授權

本專案使用 **MIT License**，見 [`LICENSE`](LICENSE)。安裝套件/可攜包內的第三方元件有各自授權，見 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)，完整文本在 `third_party/`。安全回報請依 [`SECURITY.md`](SECURITY.md) 使用 GitHub 私密漏洞回報。

## 目錄

```text
backend/
  manage.js              CLI：config.toml/.env/供應商/自動啟動管理
  server.js              本機修復代理
  start-hidden.vbs       隱藏登入入口
  callidfix.config.json  使用者設定
gui/app.py               Tkinter GUI（sv-ttk 主題）
packaging/
  installer.py           自刪除的目前使用者安裝器
  build.ps1              一鍵發佈建置
  sign.ps1               可選正式簽章
  trust-sign.ps1/.cmd    本機自簽工具
  cleanup.ps1/.cmd       可攜版/安裝版清理工具
assets/app.ico           應用程式/安裝套件圖示
.github/workflows/       CI 建置 + 可選簽章 + Release
AUTHORS.md               作者資訊
LICENSE                  MIT
stop.cmd                 CLI 捷徑（off）
```

執行時在 `backend/` 產生：`state.json`、`server.log`、`node-path.txt`、`gui.json`。安裝根目錄還有 `backup-root.txt`；安裝前快照在 `%LOCALAPPDATA%\CodexCallIdFix\backups\`。

## Windows Defender 誤報

安裝套件使用 PyInstaller onefile，且目前未簽章；Defender 可能對這類封裝程式回報 `Trojan:Win32/Wacatac.H!ml` 之類的機器學習偵測。它可能是誤報，但不要直接假設安全：

1. 下載完整檔案（不是 `.crdownload` 這種未完成下載）；
2. 用 Release 的 `SHA256SUMS.txt` 核對 SHA-256；
3. 雜湊符合後，向 Microsoft 提交誤報：
   <https://www.microsoft.com/en-us/wdsi/filesubmission>
   （選擇軟體開發者/誤報方向，附偵測名稱、Release URL、雜湊）；
4. 如需本機測試，只在雜湊確認後對該檔案單獨放行，測試完移除；不要關閉即時保護或排除整個目錄。

本機自簽不能解決 Defender/SmartScreen 信譽問題。公開發佈建議使用 CA 程式碼簽章憑證，並考慮把安裝器改成 onedir + 一般安裝框架，減少嵌套 onefile 的啟發式命中。

## 疑難排解

- **Codex 仍顯示舊錯誤**：完全結束 Codex Desktop（不是只關視窗）再啟動，讓它重新讀取 `config.toml` 和 `.env`。
- **上游代理無法連線**：狀態卡會顯示 `[無法連線]`；改用 `自動退回` 或 `直連`，或修正位址/連接埠。
- **本機連接埠被佔用**：在 GUI 修改本機連接埠；`on` 會停止記錄的舊執行個體並重新綁定。
- **`off` 拒絕停止**：某個供應商指向代理但原始 URL 未知。補到 `fallbackOriginalBaseUrls`，再執行 `off`。
- **切換 OpenAI 後模型回報錯誤**：`model` / `model_catalog_json` 仍指向上一個供應商。在 Codex 選擇 OpenAI 模型，或修改這些鍵。
- **`EPERM ... config.toml...tmp`**：目前程序執行在受限權杖下（例如 Codex 的 Windows 沙箱），對 `~/.codex` 只有讀取權限。請從開始選單或檔案總管啟動 GUI，不要從 Codex 終端啟動；`manage.js provider use` 同理。
- **在 Codex 沙箱外執行**：從受限 Codex 終端寫 `~/.codex` 可能被拒絕；用 GUI 或一般 PowerShell。
- **安裝器提示捷徑/解除安裝登錄檔失敗**：某些加固環境會拒絕未簽章 EXE 寫登錄檔或捷徑。應用程式仍會安裝並自檢；用安裝目錄的 `uninstall.cmd` 解除安裝，桌面捷徑沒建立時用開始選單捷徑。
- **“backend/manage.js not found”**：單獨一個 `CodexCallIdFix.exe` 沒有後端。請用安裝套件，或解壓 `CodexCallIdFix-0.1.6-portable.zip`；從原始碼目錄執行時，把 `backend/` 放在 EXE 同級或上一級，並提供 `runtime/node.exe` 或 PATH 中的 Node。
- **“Could not create temporary directory”**：onefile 啟動器解壓到使用者暫存目錄，不會在 EXE 旁建立 `_MEI` 資料夾。請確認 `%TEMP%` 可寫，且沒有被重新導向到唯讀位置。
- **本機自簽報 `NTE_PERM` / `0x80090010`**：目前程序在 Codex 沙箱權杖下，對 `%APPDATA%\Microsoft\Crypto\Keys` 只有讀取權限，無法建立憑證私鑰。請從開始選單或檔案總管啟動，不要從 Codex/DSH 終端啟動；不要給沙箱群組寫 Crypto ACL。
- **Codex 顯示 `openai -- (missing section)`**：`config.toml` 設定了 `model_provider = "openai"`，但沒有對應的 `[model_providers.openai]` 區段。刪除這一行可使用內建 OpenAI 供應商，或補上明確區段；這是供應商標籤/設定問題，和 `auth.json` 認證是兩回事。
- **SmartScreen 顯示「未知發行者」**：發佈的二進位檔預設未簽章；正式簽章見上面的「作者與程式碼簽章」，或在本機使用 `Trust & Sign`。
- **Windows「應用程式與功能」裡沒有項目**：用安裝目錄的 `uninstall.cmd`；它也會先執行 `manage.js off` 和 `autostart off` 再刪除檔案。
- 記錄：`backend/server.log`（5 MB 輪轉）。

## 範圍與免責聲明

這是針對 Codex Desktop 序列化 bug 的本機 workaround，不是 OpenAI/Codex 官方元件。預設只監聽 loopback，不會把你的提示詞送到已設定供應商 `base_url` 以外的地方。
