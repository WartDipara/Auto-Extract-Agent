# IM Module Conversation Protocol

Feishu and DingTalk share the same command set; only channel SDKs differ.
The bot accepts **only** the fixed formats below. Cloud spreadsheet sync is deprecated.

In group chats you must **@bot** before the body (DingTalk requires an explicit @ mention).

---

## 1. Overview


| Intent | What to send | Bot response |
| ------ | ------------ | ------------ |
| Greeting | `你好` / `hi` / `hello` … | Self-intro + usage |
| Enqueue extract | APK URL(s) (see 2) | Write Module A inbox; deliver result when done |
| Query ledger | `query …` (see 3) | Text glance |
| Export table | `export table …` (see 4) | Excel by filename (deduped) |
| Help | `help` / `?` / bare `query` / bare `export` | Usage summary |
| Other | Free text | Short reject; send `help` for full usage |


Match order: ops (greet/query/export/help) → enqueue (URLs or legacy JSON) → otherwise reject.

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
| `success` | Result file + text note (DingTalk sends `.bin` as `.zip`) |
| Failure terminal | Text: `任务结束：<label>` + `status` + `error` |
| Success but file missing too long | Timeout text (default ~10 min) |


Ledger statuses: section 4. Pipeline runs inside Module A.

---

## 3. Query ledger

Source: Module A `tasks.db` (timestamps stored **UTC** `…Z`).
Chat glances are **plain text** (~3500 char budget; times in **Asia/Shanghai** when shown).
Excel export is a **separate** command: `export table` (section 4).

Text columns for list/progress: game name · task id · status (+ short reason on failures).
Detail cards (`query gid` / `query label`) are user-facing: game name, task id, status, update time, whether result pack exists, whether group delivery happened; optional failure / delivery notes. No session/adb/hotfix.

List headers look like `【我的进行中任务】（共 N 条）` / `【全部进行中任务】` / `【状态：success】`.

### 3.1 My active tasks (asker view)

```text
@bot query mine
```

- Non-terminal statuses only, filtered by `im_sender_id` = current asker.
- Max **30** rows; if more: `showing 30/N` + hint `export table`.

### 3.2 Progress (all active)

```text
@bot query progress
```

- Non-terminal statuses only (`queued` … `extract_done`), **entire ledger**.
- Max **30** rows (internal limit); if more: `showing 30/N` + hint `export table`.

### 3.3 By status

```text
@bot query status timeout
```

- Max **20** rows (newest first). Over cap → hint `export table`.
- Invalid status → short list of allowed statuses.

### 3.4 By task id

```text
@bot query gid t-0002
```

- Exact match on `task_id` only.
- Reply shape (Shanghai times):

```text
【游戏名】
任务号：t-0002
状态：success
更新：2026-08-06 11:18:07
结果包：已生成
群回传：2026-08-06 11:20:00
```

Optional lines: `原因：…` (task error), `回传说明：…` (delivery note). Miss: `未找到：…`.

### 3.5 By label

```text
@bot query label 三国
```

- Fuzzy match on `label` (`LIKE %token%`), up to **10** rows; same card layout as §3.4.

### 3.6 Result password

```text
@bot query password
```

- Reads `ZIP_PASSWORD` from `apps/auto-extract/.env` (buf_done `.bin` pack password).
- Reply example: `解压密码：…`

### 3.7 Help

```text
@bot help
@bot ?
@bot query
@bot export
```

---

## 4. Export table

```text
@bot export table all
@bot export table success
```

- Unique by `filename` (latest `updated_at` wins).
- Columns: `filename`, `label`, `updated_at`, `finished_at`.
- Times in **Asia/Shanghai** as `YYYY-mm-DD: HH:mm`.
- `all` = every status; otherwise filter by ledger status.
- Invalid status → short allowed-status hint (includes `all`).
- Hard cap 50000 unique filenames.
- `query export` is retired and redirects to this command.

---

## 5. Ledger statuses

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
`query all` / `query top_n` are unsupported (limits are internal).

---

## 6. Explicitly unsupported

- `@bot 同步` / Feishu Bitable / DingTalk group spreadsheet → **deprecated**
- Arbitrary user SQL
- Free-form chat (always reply with usage)

---

## 7. Ops notes (not chat protocol)


| Item | Note |
| ---- | ---- |
| Channel | `IM_CHANNEL=feishu` or `dingtalk` (see `.env.example`) |
| Announce chats | Lifecycle broadcast set: pin via `ANNOUNCE_CHAT_ID` (comma-separated OK) **plus** every group that has @'d the bot (`state/announce_chat.json` → `chat_ids`). |
| Lifecycle | Online / offline / core-fault **broadcast to all** announce chats. Task results never use announce — only that task's `im_chat_id`. |
| Core heartbeat | Each registered core writes its own `state/heartbeat` every 5s (get-texts under auto-extract). IM background stale=15s; on submit uses 10s and folds a deferral note into the enqueue ack (no duplicate core-down broadcast). |
| Ledger DB | Shared file `apps/auto-extract/state/tasks.db`; **one table per module** (get-texts → `tasks`). Registry: `shared/module_registry.py`. DingTalk stores `im_sender_id` (staffId) for @-back replies. |
| Delivery | Strict `im_chat_id` only (fail-closed). Audit: `state/delivery_audit.jsonl`; last error in `im_deliver_error`. After file send success, text failure still marks delivered (no duplicate file). DingTalk: sessionWebhook @; if expired, OpenAPI group + OTO to sender. |
| Deferred enqueue | IM tracks `state/pending_inbox.json`. If core was down and the inbox file vanishes before Module A accepts it, IM rewrites the file on core-up (and notifies the submitter). |
| Timestamps | DB stores UTC `…Z`; IM displays Asia/Shanghai |
| Query export dir | default `apps/im-module/state/query_exports` (`QUERY_EXPORT_DIR`) |
| Runtime | Registered core(s) and IM both required; IM alone cannot extract |
| IM restart | Safe: unfinished deliveries re-polled from `tasks.db` (`im_chat_id` / `im_sender_id`). DingTalk also restores unexpired `sessionWebhook` from `state/dingtalk_session_replies.json` so @-back can continue after a brief outage. |


Start IM:

```powershell
cd apps/im-module
.\launch.ps1
```
