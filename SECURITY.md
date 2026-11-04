# Security policy

## Supported versions

Security fixes are provided for the latest `0.1.x` release. Older builds may be
missing fixes and should be upgraded.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** for this repository:

<https://github.com/Hungry-M/codex-callid-fix/security/advisories/new>

Do not open a public issue with exploit details, credentials, provider URLs,
API keys, `.env` contents, `auth.json`, or full request/response bodies.

Please include:

- affected version and Windows version;
- Codex Desktop/CLI version (if relevant);
- a minimal, sanitized reproduction;
- impact and any suggested fix.

## Scope

The tool runs a loopback HTTP proxy and edits Codex's `config.toml`/`.env` with
the user's permission. Security-relevant areas include:

- listening beyond loopback;
- logging or exposing credentials/prompt content;
- path/URL validation for provider routes;
- atomic configuration writes and backups;
- installer/uninstaller registry and shortcut handling;
- code signing/trust behavior.

## Design notes

- The proxy binds `127.0.0.1` by default.
- It does not terminate TLS; it forwards bytes through CONNECT or direct TLS.
- It does not log request bodies or `Authorization` headers by default.
- `manage.js off` restores tool-managed `base_url` and `.env` changes; it does
  not blindly overwrite unrelated user edits.
- Test builds may be unsigned. Code signing does not by itself make a build
  trustworthy; verify the source and checksums.
