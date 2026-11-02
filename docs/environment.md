# Test environment

Recorded: 2026-11-02 (Asia/Shanghai)

This machine is the build/development host. The `create_thread` /
`send_message_to_thread` bug has **not** been reproduced here yet; a second
machine is needed for the reproduction test.

## Codex

| Component | Version / path |
| --- | --- |
| Codex Desktop (MSIX package) | `OpenAI.Codex` **26.1027.3384.0** (x64) |
| Desktop executable | `%ProgramFiles%\WindowsApps\OpenAI.Codex_26.1027.3384.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe` |
| Desktop file version | `156.0.8078.48` |
| Codex CLI | `codex-cli 0.166.0-alpha.5.1` |
| CLI path | `%LOCALAPPDATA%\OpenAI\Codex\bin\22cfb1d302613eae\codex.exe` |

## Build host

| Component | Version |
| --- | --- |
| Windows | Windows 10 Home (Chinese), 10.0.19045, 64-bit |
| Node.js | v24.13.0 |
| Python | 3.10.0 |
| Codex Call ID Fix | 1.0.0 |

## Notes

- Codex Desktop is installed as the `OpenAI.Codex` MSIX package; the process
  name is `ChatGPT.exe`.
- The GUI and `manage.js` must be launched outside Codex's Windows sandbox.
  Inside the sandbox, `~/.codex` is read-only for `CodexSandboxUsers`, which
  causes `EPERM` when writing `config.toml`.
- Test data and `CODEX_HOME` were isolated during development; do not commit
  `.codex` contents, logs, auth files, or provider API keys.
