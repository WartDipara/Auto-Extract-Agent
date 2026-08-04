# IM Module Conversation Protocol

Feishu and DingTalk share the same command set; only channel SDKs differ.
The bot accepts **only** the fixed formats below. Cloud spreadsheet sync is deprecated.

In group chats you must **@bot** before the body (DingTalk requires an explicit @ mention).

---

## 1. Overview


| Intent | What to send | Bot response |
| ------ | ------------ | ------------ |
| Enqueue extract | JSON (see 2) | Write Module A inbox; deliver result when done |
| Query ledger | `query …` (see 3) | Read-only SQLite → CSV file (or not-found text) |
| Help | `help` / `?` / bare `query` | Usage summary |
| Other | Free text | `unknown command` + usage |


Match order: ops command (query/help) → JSON enqueue → otherwise reject.

---

## 2. Enqueue

### Format

```json
{"get-texts":{"urls":["https://example.com/game.apk"]}}
```

- Multiple URLs allowed; empty list is invalid.
- Extra prose or markdown code fences are OK; the bot extracts JSON.
- URLs are trimmed; empty/invalid entries are skipped.

### Example

```text
@bot {"get-texts":{"urls":["https://cdn.example.com/a.apk","https://cdn.example.com/b.apk"]}}
```

### Ack

```text
已入队：im_<request_id>.json
urls=<N>
```

### Per-task delivery when finished


| Result | Delivery |
| ------ | -------- |
| `success` | Result file (`.bin`) + text note; DingTalk may fall back to a path hint if file send is unsupported |
| Failure terminal | Text: `任务结束：<label>` + `status` + `error` |
| Success but file missing too long | Timeout text (default ~10 min) |


Ledger statuses: section 4. Pipeline runs inside Module A.

---

## 3. Query ledger

Source: Module A `tasks.db`.
On success: a one-line summary, then a **CSV file**. If the channel cannot send files, a local path hint is returned.

### 3.1 All rows

```text
@bot query all
```

- Hard cap 50000 rows; truncated exports include `truncated=true`.

### 3.2 Latest N

```text
@bot query top_n 20
```

- `N` must be an integer in **1–1000**.
- Ordered by `updated_at` DESC.

### 3.3 By id / filename / URL

```text
@bot query gid t-0002
@bot query gid 17498_....apk
@bot query gid https://.../game.apk
```

- Match order: `task_id` → `filename` → `url` (exact).
- Miss: text `not found: …` (no empty CSV).

### 3.4 By status

```text
@bot query status success
```

Valid `status` values: section 4. Invalid values list the allowed set.

### 3.5 Help

```text
@bot help
@bot ?
@bot query
```

---

## 4. Task status (ledger)

Status is written only at stage boundaries (not progress percentages).


| status | meaning |
| ------ | ------- |
| `queued` | Enqueued, waiting download |
| `downloaded` | APK on disk |
| `patched` | decoded + debuggable done; waiting for a device |
| `on_device` | Holding ADB (install / enter game / pull hotfix) |
| `device_done` | Device stage done; ADB released; waiting OpenCode |
| `on_extract` | Holding OpenCode |
| `extract_done` | Extract finished; waiting archive |
| `success` | Success |
| `decrypt_failed` | Decrypt failed |
| `assets_missing` | Asset texts not found |
| `abnormal_exit` | Abnormal exit |
| `failed` | Failed (incl. interrupted pipeline) |
| `timeout` | Timeout |


CSV columns typically: `task_id,url,label,filename,status,error,result_csv,session_id,buf_done_zip,source_file,adb_serial,created_at,updated_at,finished_at,im_delivered_at`.

---

## 5. Explicitly unsupported

- `@bot 同步` / Feishu Bitable / DingTalk group spreadsheet → **deprecated**
- Arbitrary user SQL
- Free-form chat (always reply with usage)

---

## 6. Ops notes (not chat protocol)


| Item | Note |
| ---- | ---- |
| Channel | `IM_CHANNEL=feishu` or `dingtalk` (see `.env.example`) |
| Ledger DB | default `apps/auto-extract/state/tasks.db` (`TASKS_DB`; IM and Module A must share the path) |
| Query export dir | default `apps/im-module/state/query_exports` |
| Runtime | Module A and IM both required; IM alone cannot extract |


Start IM:

```powershell
cd apps/im-module
.\launch.ps1
```
