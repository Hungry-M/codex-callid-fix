# Codex Call ID Fix

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md)

A local repair proxy + small Windows GUI for the Codex Desktop error:

```text
Invalid 'call_id': call_id is required for function_call_output.
```

Codex sometimes seeds child-thread tool delegations
(`create_thread` / `send_message_to_thread`) as `function_call_output` items
without a `call_id`. Strict OpenAI-compatible Responses endpoints reject that.
The proxy rewrites those synthetic items into ordinary `user` messages before
forwarding the request, so the provider sees a valid payload.

It is intentionally provider-agnostic: any `[model_providers.*]` section in
Codex's `config.toml` can be routed through it, and the listening/upstream proxy
ports are configuration values, not constants.

> **Status: experimental compatibility shim (0.1.2).** The original failure has
> not been reproduced on either available test machine, and no captured request
> is available. Do not treat this as a confirmed Codex fix; validate with
> `rewrote=` in `backend/server.log` for your provider/version.
>
> This is an independent project, not affiliated with or endorsed by OpenAI.

## Features

- Repairs synthetic `function_call_output` items (no `call_id`) in Responses
  requests.
- One local proxy can route any number of providers using
  `/_p/<provider>/...` paths.
- Start/stop the proxy without hand-editing `config.toml`.
- Switch Codex's active model provider from the GUI, including
  `OpenAI (built-in)` (removes the `model_provider` key).
- Three egress modes:
  - `proxy`: through an upstream HTTP proxy (CONNECT).
  - `direct`: direct TCP/TLS to the provider.
  - `auto`: try the upstream proxy, fall back to direct.
- Manages `~/.codex/.env` together with the route, so Codex itself follows the
  same choice when the proxy is off.
- Optional Windows logon autostart (hidden, no admin required).
- CLI and Tkinter GUI.
- Light, dark, and follow-system appearance (the GUI remembers your choice).
- Simplified Chinese, Traditional Chinese, and English UI; separate Chinese and
  English font families plus font size.
- Ports are editable in the GUI / `callidfix.config.json`.

## Install (Windows)

Download and run:

```text
CodexCallIdFix-Setup-0.1.2.exe
```

The installer is per-user (`%LOCALAPPDATA%\Programs\CodexCallIdFix`), needs no
administrator rights, copies the bundled Node runtime, creates shortcuts, and
runs an installation self-check. If the check passes, the installer deletes
itself.

If you do not want an install, extract
`CodexCallIdFix-0.1.2-portable.zip` and run `CodexCallIdFix.exe` inside it. The
portable folder contains `backend/`, `runtime/node.exe`, the docs, and the
signing helper. The bare `CodexCallIdFix.exe` alone is not a complete
distribution: it needs a sibling/parent `backend/` and a Node runtime (bundled
or on `PATH`).

After installation:

1. Open **Codex Call ID Fix**.
2. Pick your provider in the **Codex Model Provider** box.
3. Choose **Codex route**:
   - `Fix proxy (local port)` — Codex goes through this proxy.
   - `Upstream proxy` — Codex goes directly to the upstream HTTP proxy, proxy off.
   - `Direct` — Codex goes direct, proxy off.
4. If using the fix proxy, choose **Fix proxy egress**:
   `Upstream proxy` / `Direct` / `Auto fallback`.
5. Set the local listening port and upstream proxy host/port in the settings
   card. They are written to `backend/callidfix.config.json`.
6. **Completely quit and restart Codex Desktop** after changing `config.toml`, `.env`, or
   the provider.

The proxy port defaults are examples (`7891` local, `7890` upstream); change
them to anything you like in the GUI.

Interface preferences live in the **Menu → Settings…** dialog (secondary menu), not
on the main screen:

- Language: `Simplified Chinese`, `Traditional Chinese`, `English`.
- Appearance: `Follow system` / `Light` / `Dark`. Follow-system reads the Windows
  personalization setting and re-checks it every few seconds.
- Separate **Chinese font** and **English font** family selection, plus font size.
  The Chinese UI uses the Chinese font; the English UI uses the English font.

The choices are saved in `backend/gui.json` (generated runtime file).

## Backups and uninstall

Every installation/upgrade creates an automatic pre-install backup under:

```text
%LOCALAPPDATA%\CodexCallIdFix\backups\<timestamp>-v0.1.2\
  manifest.json
  codex\config.toml        (if present at install time)
  codex\.env               (if present)
  install\backend\...      (existing config/state/gui on upgrade)
```

The actual backup root is also written to `backup-root.txt` in the install
folder. This snapshot is for **manual disaster recovery**; it is not blindly
copied back over `config.toml`, because that would discard changes you made
after installation.

Uninstall (`uninstall.cmd`, also used by Windows **Apps & features** when the
registry entry was created) does this in order:

1. `manage.js off` — restores tool-managed `base_url` values, restores/parks
   `.env` according to the current egress mode, and stops the proxy.
2. `manage.js autostart off` — removes the logon autostart entry.
3. Removes the uninstall registry key, Run value, and Start Menu/Desktop
   shortcuts.
4. Removes the install directory.
5. Deletes the backup root **only after step 1 succeeded**.

If step 1 fails (for example a provider's original URL is unknown), uninstall
shows a warning, keeps both the installation and the backup, and exits without
deleting anything. Fix `fallbackOriginalBaseUrls` or the provider section, then
run `uninstall.cmd` again.

## Testing on another PC

The original failure has not been reproduced on the development host or the
second test machine, and no captured request is available. Versions recorded on
the development machine are in [`docs/environment.md`](docs/environment.md); the
checklist for a future observed case is in [`docs/reproduce.md`](docs/reproduce.md).
Do not attach `.codex` auth/state or API keys to an issue.

## Egress modes

**Fix proxy egress** only applies when **Codex route = Fix proxy**. It controls
how the fix proxy reaches the provider:

- `Upstream proxy` — the fix proxy connects to the configured HTTP proxy
  (`proxyHost:proxyPort`), sends `CONNECT <provider>:443`, then forwards the
  request. Use this when the provider is only reachable through that proxy.
- `Direct` — the fix proxy opens a raw TCP/TLS connection to the provider and
  bypasses the upstream proxy and Windows system proxy.
- `Auto fallback` — try the upstream proxy first (bounded by `autoProbeMs`,
  3 seconds by default); if the TCP/CONNECT step fails, retry directly. If the
  upstream proxy accepts the connection but the provider returns an HTTP error,
  it does **not** retry direct.

## How it works

```text
Codex
  -> http://<listenHost>:<listenPort>/_p/<provider>/<original path>
  -> codex-callid-fix (rewrites body)
  -> upstream HTTP proxy  or  direct TCP/TLS
  -> the provider's original base_url
```

`on` rewrites the provider's `base_url` like this:

```toml
[model_providers.MyProvider]
base_url = "https://api.example.com/v1"
```

to:

```toml
[model_providers.MyProvider]
base_url = "http://127.0.0.1:7891/_p/MyProvider/v1"
```

The `/_p/<provider>/` prefix lets one listening port serve several providers.
`off` scans **all** `[model_providers.*]` sections and restores any `base_url`
that points at this proxy.

Original URLs are maintained in two places:

1. `backend/state.json` — `originalBaseUrls` (recorded by `on`);
2. `backend/callidfix.config.json` — `fallbackOriginalBaseUrls` (automatically
   published by `on`, used if `state.json` is lost).

Only the `base_url` line is changed; comments, other keys, BOM, and line endings
are preserved. If the original URL cannot be determined, `off` refuses to stop
rather than leaving Codex pointed at a dead proxy.

## Provider switching

The GUI lists:

- `OpenAI (built-in)` — deletes the top-level `model_provider` key, letting
  Codex use its built-in provider.
- Every `[model_providers.<id>]` found in `~/.codex/config.toml`.

Selecting a custom provider writes `model_provider = "<id>"`. It does **not**
change `model` or `model_catalog_json`; if Codex reports an unknown model after
switching, choose the matching model in Codex's model picker (or update
`model_catalog_json` yourself). This is deliberate: model names are
provider-specific and the tool should not guess.

The proxy manages **all** custom providers by default
(`"providers": "all"`), so switching the active provider does not require
re-applying the proxy. To manage only a subset, use an explicit array:

```json
"providers": [
  "MyProvider",
  { "id": "AnotherProvider", "egress": "direct" }
]
```

Per-provider `egress` overrides the global mode while the proxy is on.

## Codex `.env`

The route selector also controls `~/.codex/.env`:

- `proxy` / `auto`: ensure `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` point at the
  configured upstream proxy, and merge `localhost,127.0.0.1,::1` into
  `NO_PROXY`.
- `direct`: remove those proxy variables. If the file only contained proxy
  variables it is deleted; the content is saved to
  `~/.codex/.env.callidfix-parked` and restored when switching back.
- Other variables (API keys) are preserved.
- The first edit creates `~/.codex/.env.callidfix-backup`.

Changes to `.env` require a Codex Desktop restart.

If your proxy client also sets the **Windows system proxy**, deleting `.env`
alone may not force Codex direct; disable the system proxy in that client. The
fix proxy's own `direct` mode uses raw TCP/TLS and ignores system proxy
settings.

## Autostart

Enable **Start automatically at Windows sign-in (hidden)** in the GUI, or:

```powershell
node backend/manage.js autostart on
node backend/manage.js autostart status
node backend/manage.js autostart off
```

This writes an `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value named
`codex-callid-fix`. At logon, `start-hidden.vbs` runs `manage.js boot`, which
reconciles the last on/off state: if the proxy was ON it starts it and repairs
`config.toml`/`.env`; if it was OFF it stops stray processes and leaves the
configuration direct. No administrator rights are needed.

## CLI

The GUI is a front-end for the same CLI:

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

Examples:

```powershell
# point all custom providers at the fix proxy, direct outbound
node backend/manage.js route fix direct

# stop the proxy; Codex uses the upstream proxy directly
node backend/manage.js route upstream

# stop the proxy; Codex goes direct
node backend/manage.js route direct

# switch Codex to the built-in OpenAI provider
node backend/manage.js provider use openai
```

Health check:

```powershell
curl.exe http://127.0.0.1:7891/__callidfix/health
```

## Configuration

`backend/callidfix.config.json`:

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

- `listenPort`: local fix-proxy port. Change it in the GUI or here; `on`/`restart`
  rebinds and rewrites `base_url`s.
- `egress.proxyHost` / `proxyPort`: upstream HTTP proxy. Use any port; nothing
  is hard-coded in the proxy logic.
- `egress.mode`: `proxy`, `direct`, or `auto`.
- `providers`: `"all"` or an explicit array.
- `fallbackOriginalBaseUrls`: automatically populated by `on`; can also be
  edited manually for recovery.
- `codexEnv.manage`: set `false` if you do not want the tool to touch
  `~/.codex/.env`.

## Build from source

Requirements: Windows 10/11, Python 3.10+, PyInstaller, `sv-ttk`, Node.js (for
running the backend during development and for staging the runtime).

```powershell
python -m pip install pyinstaller sv-ttk
node --test
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1
```

`node --test` runs the rewrite tests in `tests/` without external dependencies.

Outputs:

```text
dist/CodexCallIdFix.exe
dist/CodexCallIdFix-Setup-0.1.2.exe
dist/CodexCallIdFix-0.1.2-portable.zip
dist/SHA256SUMS.txt
```

Development run:

```powershell
python gui/app.py
node backend/manage.js status
```

The installer embeds the GUI exe, `backend/`, a portable `node.exe`, the icon,
`README.md`, `README.zh.md`, `README.zh-Hant.md`, `LICENSE`, and
`AUTHORS.md`. The uninstaller is written to the install directory and registered
under Windows **Apps & features** (per-user).

A GitHub Actions workflow (`.github/workflows/build.yml`) builds on every push
and attaches the EXEs/checksums to a release when a `v*` tag is pushed.

## Author and code signing

Author metadata lives in `AUTHORS.md`, the PyInstaller version resources, and
the installer's `Publisher` value. The author is **Hungry-M**
(<https://github.com/Hungry-M>). No email address is embedded in the
binaries or package metadata; a GitHub `noreply` address is fine for commits and
open-source metadata.

The release binaries are **not signed by default**. Unsigned builds work, but
Windows SmartScreen shows "Unknown publisher". To sign:

1. Obtain an Authenticode code-signing certificate (OV or EV). For public
   releases prefer a CA-issued certificate; a self-signed certificate is not
   trusted by other users. The CA requires a verifiable real identity/contact,
   so a `noreply` email is not enough for the certificate itself.
2. Never commit the `.pfx` or its password. Use a secret store / CI secret.
3. After `packaging/build.ps1`, run:

```powershell
# PFX file
$env:CODESIGN_PFX = 'C:\secure\codesign.pfx'
$env:CODESIGN_PFX_PASSWORD = '...'
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/sign.ps1

# or a certificate already imported into the user's certificate store
$env:CODESIGN_THUMBPRINT = 'ABCDEF...'
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/sign.ps1
```

`signtool.exe` comes from the Windows SDK. CI can sign automatically by setting
the `CODESIGN_PFX_BASE64` and `CODESIGN_PFX_PASSWORD` repository secrets.

### Local self-signing (this machine only)

The installer includes:

```text
trust-sign.cmd
trust-sign.ps1
```

After installation you can run **Start Menu → Trust & Sign Codex Call ID Fix**
(or the GUI menu **Menu → Trust & sign locally…**). It:

1. creates (or reuses) a local root CA in `Cert:\CurrentUser\My`
   (`CN=Hungry-M`) and trusts it in `CurrentUser\Root`;
2. creates a project child certificate signed by that root
   (`CN=codex-callid-fix`) and adds it to `CurrentUser\TrustedPublisher`;
3. waits for the GUI to close, signs `CodexCallIdFix.exe` with the child using
   SHA-256, then relaunches it (even if signing failed; failures are logged to
   `%LOCALAPPDATA%\CodexCallIdFix\trust-sign.log`).

The root can be shared by other local projects; each project should get its own
child certificate under the same root. `-RemoveCert` removes the project child
first, then removes the root **only if no other child certificates issued by it
remain**. The installer's uninstaller calls the same cleanup.

Root sharing is **local-only**. Installing app A does not make a separately
downloaded app B trusted on another user's machine; A's installer would have to
explicitly add the root to the user's Root store, which this project does not do
and does not recommend. Use a CA-issued certificate for public distribution.

This makes the file signed by a **locally trusted** publisher, so File
Properties → Digital Signatures should show the signer. It **does not** make
other computers trust the file, and SmartScreen reputation may still show a
warning for a self-signed or downloaded file. Only use it on a machine you
control. Remove the local certificate later with:

```powershell
trust-sign.cmd -RemoveCert
```

`-RemoveCert` removes the `CN=codex-callid-fix` child from `My` /
`TrustedPublisher`, and removes the `CN=Hungry-M` root only when no other
project child certificate remains. It uses `certutil -user -delstore` because
PowerShell refuses to delete items from the current user's Root store directly.

## License

The project is licensed under the **MIT License**; see [`LICENSE`](LICENSE).
Bundled/third-party components have their own terms; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Security reports should use
GitHub private vulnerability reporting per [`SECURITY.md`](SECURITY.md).
Contributions use DCO sign-off plus a lightweight inbound relicense grant; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Layout

```text
backend/
  manage.js              CLI: config.toml/.env/provider/autostart management
  server.js              local repair proxy
  rewrite.js             synthetic call_id rewrite logic
  start-hidden.vbs       hidden logon entry
  callidfix.config.json  user configuration
gui/app.py               Tkinter GUI (sv-ttk theme)
tests/rewrite.test.js    Node rewrite tests (`node --test`)
packaging/
  installer.py           self-deleting per-user installer
  build.ps1              one-command release build
  sign.ps1               optional Authenticode signing
  trust-sign.ps1/.cmd    local self-signing helper (installed with the app)
assets/app.ico           application/installer icon
.github/workflows/       CI build + optional signing + release
AUTHORS.md               author metadata
LICENSE                  MIT
THIRD_PARTY_NOTICES.md   bundled dependency licenses
third_party/             full third-party license texts
SECURITY.md              vulnerability reporting
CODE_OF_CONDUCT.md       community behavior
CONTRIBUTING.md          development and test notes
CHANGELOG.md             release history
stop.cmd                 CLI shortcut for "off"
README.zh.md             Simplified Chinese documentation
README.zh-Hant.md        Traditional Chinese documentation
```

Generated at runtime in `backend/`: `state.json`, `server.log`, `node-path.txt`,
`gui.json` (GUI appearance preference). The install root also contains
`backup-root.txt`; pre-install snapshots live under
`%LOCALAPPDATA%\CodexCallIdFix\backups\`.

## Troubleshooting

- **Codex still shows the old error** — fully quit Codex Desktop (not just close
  the window) and start it again so it re-reads `config.toml` and `.env`.
- **Upstream proxy unreachable** — the status card shows `[unreachable]`; use
  `Auto fallback` or `Direct`, or fix the host/port.
- **Local port already in use** — change the local port in the GUI; `on` stops
  the recorded old instance and rebinds.
- **`off` refuses to stop** — a provider points at the proxy but its original
  URL is unknown. Add it to `fallbackOriginalBaseUrls`, then run `off` again.
- **OpenAI model error after switching** — `model`/`model_catalog_json` still
  point at the previous provider. Pick an OpenAI model in Codex or edit those
  keys.
- **`EPERM ... config.toml...tmp`** — the process is running under a restricted
  token (for example Codex's Windows sandbox), which has read-only access to
  `~/.codex`. Start the GUI from the Start Menu or Explorer instead of a Codex
  terminal. The same applies to `manage.js provider use`.
- **Run outside Codex's sandbox** — writing `~/.codex` from a restricted Codex
  terminal may be denied; use the GUI or a normal PowerShell.
- **Installer warns about shortcuts / uninstall registry** — some hardened
  environments deny shortcut or registry writes to unsigned EXEs. The app still
  installs and self-checks; run `uninstall.cmd` from the install folder to remove
  it, and use the Start Menu shortcut if the Desktop one was skipped.
- **"backend/manage.js not found"** — a bare `CodexCallIdFix.exe` cannot run
  without the backend. Use the installer or extract
  `CodexCallIdFix-0.1.2-portable.zip`; if running from a source checkout, keep
  `backend/` next to (or one level above) the EXE and provide Node via
  `runtime/node.exe` or `PATH`.
- **"Could not create temporary directory"** — the onefile launcher extracts
  next to the EXE (`--runtime-tmpdir "."`). Run it from a writable folder
  (install folder / Downloads / Desktop), not from a read-only location such as
  `Program Files` or a read-only network share. Start Menu shortcuts already set
  the install folder as the working directory.
- **`NTE_PERM` / `0x80090010` when self-signing** — the app is running under
  Codex's sandbox token, which has read-only access to
  `%APPDATA%\Microsoft\Crypto\Keys`; Windows cannot create the certificate
  private key. Launch the installed app from the Start Menu or Explorer, not
  from a Codex/DSH terminal, then retry. Do not grant the sandbox group write
  access to the crypto store.
- **SmartScreen says "Unknown publisher"** — the release binaries are unsigned
  unless you sign them. See "Author and code signing" above, or use the local
  `Trust & Sign` helper for this machine.
- **Windows Apps entry missing** — use `uninstall.cmd` in the install folder;
  it also calls `manage.js off` and `autostart off` before deleting the files.
- Logs: `backend/server.log` (rotated at 5 MB).

## Scope / disclaimer

This is a local workaround for a Codex Desktop serialization bug, not an
OpenAI/Codex official component. It only listens on loopback by default and
does not send your prompts anywhere except the provider `base_url` you already
configured.
