# Changelog

All notable changes are documented here. This project is pre-1.0; behavior may
change between 0.1.x releases.

## 0.1.1 — unreleased (prepared)

- Add automated tests for the synthetic `function_call_output` rewrite.
- Add CI test step and public-release documentation
  (`SECURITY.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`).
- Improve the menu button gap between label and chevron for all font sizes.
- Clarify that the tool is an experimental compatibility shim: the original
  failure was not reproducible on the two available test machines.

## 0.1.0 — 2026-11-02

- Initial private release.
- Local repair proxy for missing `function_call_output.call_id`.
- Tkinter GUI with simplified/traditional Chinese and English UI.
- Config.toml and `.env` management, provider switching, autostart.
- Per-user installer, portable ZIP, local self-signing helper.
