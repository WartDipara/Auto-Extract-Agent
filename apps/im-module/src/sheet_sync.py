"""Bitable → inbox sync with local seen-url store and per-row fault tolerance."""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

import config
from feishu_bitable.client import BitableClient, BitableError
from feishu_bitable.schema import (
    FIELD_DOWNLOAD_URL,
    FIELD_LAST_SYNC_AT,
    FIELD_REDO,
    FIELD_SYNC_STATUS,
    RowDecision,
    decide_row,
    parse_row,
)

_log = logging.getLogger(__name__)
_seen_lock = threading.Lock()


@dataclass
class SyncResult:
    queued_urls: list[str] = field(default_factory=list)
    decisions: list[RowDecision] = field(default_factory=list)
    writeback_ok: bool = True
    writeback_error: str = ""
    error: str = ""
    _client: Any = field(default=None, repr=False, compare=False)

    @property
    def queued(self) -> int:
        return len(self.queued_urls)

    @property
    def skipped(self) -> int:
        return sum(
            1
            for d in self.decisions
            if d.status in ("skipped_dup", "skipped_dup_in_sheet")
        )

    @property
    def invalid(self) -> int:
        return sum(1 for d in self.decisions if d.status == "invalid")

    def summary_text(self) -> str:
        if self.error:
            return f"同步失败：{self.error}"
        lines = [
            f"同步完成：新增 {self.queued}，跳过重复 {self.skipped}，非法 {self.invalid}"
        ]
        samples = [d for d in self.decisions if d.status == "invalid"][:5]
        for d in samples:
            label = d.game_name or d.record_id
            lines.append(f"非法：{label} 原因={d.reason}")
        if not self.writeback_ok:
            lines.append(
                f"入队成功但表状态未写回：{self.writeback_error or 'unknown'}"
            )
        return "\n".join(lines)


def is_sync_command(text: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw:
        return False
    commands = config.FEISHU_SYNC_COMMANDS or ("同步", "sync")
    return raw in commands


def load_seen(path: Path | None = None) -> set[str]:
    target = Path(path) if path is not None else config.SHEET_SEEN_FILE
    with _seen_lock:
        return _load_seen_unlocked(target)


def save_seen(urls: set[str], path: Path | None = None) -> None:
    target = Path(path) if path is not None else config.SHEET_SEEN_FILE
    with _seen_lock:
        _save_seen_unlocked(target, set(urls))


def mark_urls_seen(urls: list[str], path: Path | None = None) -> None:
    if not urls:
        return
    target = Path(path) if path is not None else config.SHEET_SEEN_FILE
    with _seen_lock:
        seen = _load_seen_unlocked(target)
        seen.update(u for u in urls if u)
        _save_seen_unlocked(target, seen)


def _load_seen_unlocked(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass
        _log.warning("sheet seen corrupted, reset empty: %s (%s)", path, exc)
        return set()
    urls = data.get("urls") if isinstance(data, dict) else None
    if not isinstance(urls, list):
        return set()
    return {str(u).strip() for u in urls if str(u).strip()}


def _save_seen_unlocked(path: Path, urls: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "urls": sorted(urls),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sync_from_bitable(
    client: BitableClient | None = None,
    *,
    seen_path: Path | None = None,
) -> SyncResult:
    """Read Bitable and decide per row. Does not mutate seen until commit_sync()."""
    result = SyncResult()
    if client is None:
        if not (
            config.FEISHU_APP_ID
            and config.FEISHU_APP_SECRET
            and config.FEISHU_BITABLE_APP_TOKEN
            and config.FEISHU_BITABLE_TABLE_ID
        ):
            result.error = (
                "缺少 FEISHU_BITABLE_APP_TOKEN / FEISHU_BITABLE_TABLE_ID "
                "或 FEISHU_APP_ID / FEISHU_APP_SECRET"
            )
            return result
        client = BitableClient(
            config.FEISHU_APP_ID,
            config.FEISHU_APP_SECRET,
            app_token=config.FEISHU_BITABLE_APP_TOKEN,
            table_id=config.FEISHU_BITABLE_TABLE_ID,
        )
    result._client = client

    try:
        records = client.list_records()
    except (BitableError, OSError, requests.RequestException) as exc:
        result.error = str(exc) or exc.__class__.__name__
        return result

    if _missing_download_url_column(records):
        result.error = f"表格缺少列 {FIELD_DOWNLOAD_URL}"
        return result

    seen_file = Path(seen_path) if seen_path is not None else config.SHEET_SEEN_FILE
    seen = load_seen(seen_file)
    sheet_seen: set[str] = set()
    decisions: list[RowDecision] = []
    for record in records:
        row = parse_row(record)
        if row is None:
            continue
        decision = decide_row(row, seen=seen, sheet_seen=sheet_seen)
        decisions.append(decision)
        if decision.url:
            sheet_seen.add(decision.url)
        if decision.status == "queued":
            result.queued_urls.append(decision.url)
            # Tentatively treat as seen within this pass only (sheet_seen already).
            seen.add(decision.url)

    result.decisions = decisions
    return result


def commit_sync(
    result: SyncResult,
    *,
    seen_path: Path | None = None,
) -> SyncResult:
    """After inbox write succeeds: persist seen urls and write back row statuses."""
    if result.error:
        return result
    mark_urls_seen(result.queued_urls, path=seen_path)

    client = result._client
    if client is None:
        return result
    now = dt.datetime.now().isoformat(timespec="seconds")
    updates = [_status_fields(d, now) for d in result.decisions]
    try:
        client.batch_update(updates)
    except (BitableError, OSError, requests.RequestException) as exc:
        result.writeback_ok = False
        result.writeback_error = str(exc) or exc.__class__.__name__
        _log.warning("bitable writeback failed: %s", exc)
    return result


def _missing_download_url_column(records: list[dict[str, Any]]) -> bool:
    non_empty = [
        r for r in records if isinstance(r.get("fields"), dict) and r["fields"]
    ]
    if not non_empty:
        return False
    return all(FIELD_DOWNLOAD_URL not in r["fields"] for r in non_empty)


def _status_fields(decision: RowDecision, now: str) -> dict[str, Any]:
    status = decision.status
    if status == "skipped_dup_in_sheet":
        status = "skipped_dup"
    fields: dict[str, Any] = {
        FIELD_SYNC_STATUS: status,
        FIELD_LAST_SYNC_AT: now,
    }
    if decision.status == "queued":
        fields[FIELD_REDO] = ""
    return {"record_id": decision.record_id, "fields": fields}
