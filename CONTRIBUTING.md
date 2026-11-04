# Contributing

## Development setup

Requirements:

- Windows 10/11
- Node.js 20+ (24.x used during development)
- Python 3.10+
- `pyinstaller`, `sv-ttk`

```powershell
python -m pip install pyinstaller sv-ttk
node --test
python -m py_compile gui/app.py packaging/installer.py
```

Run the GUI:

```powershell
python gui/app.py
```

Build release artifacts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1
```

## Tests

- The rewrite logic lives in `backend/rewrite.js`; tests are in `tests/`.
- Run `node --test` from the repository root.
- Manual proxy/installer tests use a temporary `CODEX_HOME` and
  `CALLIDFIX_DATA_DIR`; never point tests at a real `~/.codex`.
- For installer tests, use `--silent --no-shortcuts --no-registry --no-launch`
  and a temporary directory.

## Pull requests

- Keep changes focused; include tests for rewrite/TOML/.env behavior.
- Do not commit `auth.json`, `.env`, API keys, provider URLs, or full request
  bodies. If a report needs a provider example, use a placeholder such as
  `https://api.example.com/v1`.
- Update `CHANGELOG.md` for user-visible changes.
- Update README/README.zh/README.zh-Hant when behavior or filenames change.
- Keep version strings in sync:
  - `backend/manage.js`, `backend/server.js`
  - `gui/app.py`
  - `packaging/installer.py`, `packaging/build.ps1`
  - `packaging/version_gui.txt`, `packaging/version_installer.txt`
  - README/docs/workflow asset names

## Reporting provider compatibility

Open an issue with:

- Codex Desktop/CLI version;
- provider type (not the private URL);
- model name if it is public;
- whether `rewrote` in `backend/server.log` was 0 or greater;
- sanitized error text.

Do not paste credentials or complete prompts.
