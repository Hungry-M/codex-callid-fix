@echo off
rem Fully disable the fix proxy: restore config.toml base_url(s), stop the proxy,
rem and reconcile ~/.codex/.env with the current egress mode.
node "%~dp0backend\manage.js" off
