# IM Module Conversation Protocol

Feishu and DingTalk share the same command set; only channel SDKs differ.
The bot accepts **only** the fixed formats below. Cloud spreadsheet sync is deprecated.

In group chats you must **@bot** before the body (DingTalk requires an explicit @ mention).

---

## 1. Overview


| Intent | What to send | Bot response |
| ------ | ------------ | ------------ |
| Enqueue extract | APK URL(s) (see 2) | Write Module A inbox; deliver result when done |
| Query ledger | `query …` (see 3) | Read-only SQLite → compact **text** (no CSV) |
| Help | `help` / `?` / bare `query` | Usage summary |
| Other | Free text | `unknown command` + usage |


Match order: ops command (query/help) → enqueue (URLs or legacy JSON) → otherwise reject.

---

## 2. Enqueue

### Format (preferred)

Paste one or more `http://` / `https://` URLs after `@bot`. One per line, or space-separated on one line.

```text
@bot https://cdn.example.com/a.apk
https://cdn.example.com/b.apk
```

- Extra words around URLs are OK; the bot extracts `http(s)://…` tokens.
- Duplicate URLs are dropped (order preserved).
- No URL → rejected.

Inbox still stores the Module A schema:

```json
{"get-texts":{"urls":["https://cdn.example.com/a.apk","https://cdn.example.com/b.apk"]}}
```

Legacy chat JSON / markdown code-fence JSON in that shape is still accepted.

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

Source: Module A `tasks.db` (timestamps stored **UTC** `…Z`).
Replies are **plain text only** (chat length capped ~3500 chars). Displayed times use **Asia/Shanghai**.

Columns shown: `task_id`, `label`, `status`; failure lists may append a short `error`; `query gid` also shows Shanghai `updated_at`.

### 3.1 Progress (active queue)

```text
@bot query progress
```

- Non-terminal statuses only (`queued` … `extract_done`).
- Max **30** rows; no error/time noise.

### 3.2 All / latest N / status

```text
@bot query all
@bot query top_n 10
@bot query status timeout
```

- `all` / `status`: max **20** rows (newest first).
- `top_n`: `N` in **1–30**.
- Truncation footer points to `query gid` / `query top_n`.

### 3.3 By id / filename / URL

```text
@bot query gid t-0002
@bot query gid 17498_....apk
@bot query gid https://.../game.apk
```

- Match order: `task_id` → `filename` → `url` (exact).
- Miss: `not found: …`.

### 3.4 Help

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


Chat shows a slim subset; full fields remain in `tasks.db`.

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
| Timestamps | DB stores UTC `…Z`; IM displays Asia/Shanghai |
| Runtime | Module A and IM both required; IM alone cannot extract |


Start IM:

```powershell
cd apps/im-module
.\launch.ps1
```
