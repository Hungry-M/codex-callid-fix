# Test environment

Recorded: 2026-11-02 (Asia/Shanghai)

This machine is the build/development host. The original failure has **not**
been reproduced on either this host or the second test machine, and no captured
request is available. Treat the rewrite as an experimental compatibility shim,
not a confirmed fix.

## Codex

| Component | Version / path |
| --- | --- |
| Codex Desktop (MSIX package) | `OpenAI.Codex` **26.1027.3384.0** (x64) |
| Desktop executable | `%ProgramFiles%\WindowsApps\OpenAI.Codex_<version>_x64__<publisher>\app\ChatGPT.exe` |
| Desktop file version | `156.0.8078.48` |
| Codex CLI | `codex-cli 0.166.0-alpha.5.1` |
| CLI path | `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` |

## Build host

| Component | Version |
| --- | --- |
| Windows | Windows 10 22H2 build 19045, 64-bit |
| Node.js | v24.13.0 |
| Python | 3.10.0 |
| Codex Call ID Fix | 0.1.4 |

## Notes

- Codex Desktop is installed as the `OpenAI.Codex` MSIX package; the process
  name is `ChatGPT.exe`.
- The GUI and `manage.js` must be launched outside Codex's Windows sandbox.
  Inside the sandbox, `~/.codex` is read-only for `CodexSandboxUsers`, which
  causes `EPERM` when writing `config.toml`.
- Test data and `CODEX_HOME` were isolated during development; do not commit
  `.codex` contents, logs, auth files, or provider API keys.
