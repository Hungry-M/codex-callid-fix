# Changelog

All notable changes are documented here. This project is pre-1.0; behavior may
change between 0.1.x releases.

## 0.1.6 — 2026-11-11

- Fix the settings dialog note wrapping: use an explicit sentence break, wider
  wrap length, and a wider dialog so “English 界面” is not split at the wrong
  point.
- Record the 2026-11-11 reproduction: with the original provider and restored
  quota, the missing-`call_id` failure was observed and enabling the fix proxy
  resolved it.

## 0.1.5 — 2026-11-11

- Adapt to Codex 0.134+ profile removal: stop writing the legacy
  `profile = "<name>"` selector and `[profiles.*]` tables.
- Read official `<provider>.config.toml` profile layers and overlay their
  managed keys into the Desktop top-level config.
- On the first switch, snapshot the current provider settings into
  `<current>.config.toml`; never overwrite an existing snapshot.
- If the target has no profile, clear stale `model` / `model_catalog_json`
  instead of carrying the previous provider's values.
- Import legacy `[profiles.*]` values into `<provider>.config.toml` when no
  official profile exists, with a warning to remove the old table.

## 0.1.4 — 2026-11-08

- Clear PyInstaller bootstrap variables (`_MEIPASS2`, `_MEIPASS`, `_PYI*`)
  before relaunching after self-signing. A onefile GUI passed its stale
  `_MEIPASS2` to the helper, so the new process tried to reuse the old `_MEI`
  directory and failed with `Failed to load Python DLL ...\python310.dll`.
- Wait briefly before the relaunch to let the security scanner release the
  freshly signed EXE.
- Add `cleanup.cmd -RemoveRoot` to purge the local `CN=Hungry-M` root and all of
  its child certificates for a machine being reset; without it, the shared root
  is retained while another project child exists.
- Document the Codex `openai -- (missing section)` provider-label issue and the
  `model_provider` / `[model_providers.*]` relationship.
- Switching providers now prefers a matching `[profiles.<name>]` and sets the
  top-level `profile`, so provider-specific model/catalog/approval settings are
  loaded together.
- Portable builds create a one-time `config.toml.callidfix-backup` before the
  first config write; it is never overwritten by later switches.
- Disable (grey out) the fix-proxy egress selector when the Codex route is not
  `fix`.

## 0.1.3 — 2026-11-08

- Add `cleanup.cmd` / `cleanup.ps1` to portable and installed builds. It restores
  tool-managed Codex config, disables autostart, removes the project child
  certificate (and the root only when unused), removes matching Run/uninstall
  entries and shortcuts, and optionally removes backups.
- Stop extracting the onefile `_MEI…` directory next to the EXE; use the
  user's temp directory instead.
- Remove the bare `CodexCallIdFix.exe` from release assets; ship only the setup
  and portable ZIP.

## 0.1.2 — 2026-11-06

- Fix the local self-signing flow: wait for the exact GUI process, retry while
  the EXE is locked, verify the signature is `Valid`, log to
  `%LOCALAPPDATA%\CodexCallIdFix\trust-sign.log`, and relaunch even when signing
  fails.
- Use a reusable `CN=Hungry-M` local root CA with a project child certificate
  (`CN=codex-callid-fix`); other projects can share the root.
- Uninstall removes the project child, keeps the root while other project child
  certificates remain, and removes the root only when unused.
- Clarify that self-signing changes the local publisher/signature state but does
  not guarantee SmartScreen reputation.

## 0.1.1 — 2026-11-05

- Add automated tests for the synthetic `function_call_output` rewrite.
- Add CI test step and public-release documentation
  (`SECURITY.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`).
- Add DCO sign-off policy and pull-request check, plus a lightweight inbound
  relicense grant for contributions.
- Improve the menu button gap between label and chevron for all font sizes.
- Clarify that the tool is an experimental compatibility shim: the original
  failure was not reproducible on the two available test machines.

## 0.1.0 — 2026-11-02

- Initial private release.
- Local repair proxy for missing `function_call_output.call_id`.
- Tkinter GUI with simplified/traditional Chinese and English UI.
- Config.toml and `.env` management, provider switching, autostart.
- Per-user installer, portable ZIP, local self-signing helper.
