# Ops Runbook

Three long-running processes. Start all three after reboot.

| Process | Launch | Log |
| ------- | ------ | --- |
| Core (auto-extract) | `.\launch_auto_extract.ps1` | `apps/auto-extract/state/service.log` |
| IM | `.\launch_im_module.ps1` | `apps/im-module/state/service.log` |
| GC | `.\launch_gc_module.ps1` | `apps/gc-module/state/service.log` |

GC one-shot / dry-run: `.\launch_gc_module.ps1 -Once` / `-Once -DryRun`.

## Keep-alive (Windows)

Prefer **nssm** or Task Scheduler “At startup / Restart on failure” for each `launch_*.ps1`.
Do not rely on an interactive PowerShell window.

## Health

- Each core module writes its own `state/heartbeat` (get-texts: `apps/auto-extract/state/heartbeat`, ~5s).
- IM treats a module heartbeat older than **15s** as down (submit probe uses **10s**). With multiple cores registered, all must be healthy.
- Per-process `state/service.log` rotates at 5MB × 3.

## Task truth

- Shared ledger file: `apps/auto-extract/state/tasks.db` (one file; **one table per product module**).
- get-texts table: `tasks` (today the only registered module).
- Module paths / table names: `shared/module_registry.py`.
- Chat: `@Lino query progress` / `query status …` / `query gid <id>`
- `query gid` shows delivered time, whether `.bin` exists, session, adb.
- Secrets / channel keys: `apps/auto-extract/.env`, `apps/im-module/.env` only.

## Common failures

| Symptom | Check |
| ------- | ----- |
| IM says core down | Core process + heartbeat file age |
| Success but no file in chat | `query gid` → `buf_done` / `delivered`; IM log; `.bin` under `apps/auto-extract/buf_done/` |
| Status flipped to failed after success | error `[BUF_DONE_PACK@archive]` → pack password / disk |
| Disk filling | GC running? undelivered tasks block reclaim until IM delivers |
