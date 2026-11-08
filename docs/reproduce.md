# Reproducing the Codex `create_thread` bug

Neither the development host nor the second test machine reproduced the
failure, and no captured request is available. Keep this checklist for a future
observed case; do not assume the proxy fixes a case unless `backend/server.log`
shows `rewrote=1` (or more).

## Before testing

1. Record the machine's Codex versions:

   ```powershell
   Get-AppxPackage OpenAI.Codex | Select-Object Name,Version,InstallLocation
   & "$env:LOCALAPPDATA\OpenAI\Codex\bin\*\codex.exe" --version
   ```

   The wildcard path may need the actual `bin\<hash>\codex.exe` path; copy the
   version into `environment.md` or a new file under `docs/`.

2. Install `CodexCallIdFix-Setup-0.1.4.exe` (or extract the portable zip) and
   launch **outside** Codex's sandbox (Start Menu / Explorer, not a Codex
   terminal).

3. Confirm the backend sees the provider:

   ```powershell
   node backend/manage.js status --json
   node backend/manage.js provider list
   ```

## Reproduction steps

1. In Codex Desktop, select the provider that should use the fix.
2. In Codex Call ID Fix, set **Codex route** to `Fix proxy (local port)` and
   **Fix proxy egress** to `Upstream proxy` or `Direct`.
3. Click **Start fix proxy**; confirm `config.toml` now points at
   `http://127.0.0.1:<port>/_p/<provider>/...`.
4. Fully quit and restart Codex Desktop.
5. Trigger a prompt/tool flow that calls `create_thread` and
   `send_message_to_thread`, including a child-thread tool call.
6. Compare:
   - proxy **on**: the child call should succeed;
   - proxy **off** (route `Direct` or `Upstream proxy`): the original
     `Invalid 'call_id'...` error should return.
7. Capture from the test machine:
   - Codex Desktop/CLI versions;
   - the exact error text (screenshot or log);
   - `backend/server.log` (remove auth headers/API keys first);
   - whether the request body contained a synthetic `function_call_output`
     without `call_id`.

## Report

Open a private issue in this repository with the versions, the failing flow,
and sanitized logs. Do **not** attach `.codex` state, `auth.json`, `.env`, API
keys, or full request bodies containing credentials.
