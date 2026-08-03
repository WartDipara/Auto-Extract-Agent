"""Parse / validate Bitable rows for download_url sync."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

FIELD_DOWNLOAD_URL = "download_url"
FIELD_GAME_NAME = "game_name"
FIELD_REDO = "redo"
FIELD_SYNC_STATUS = "sync_status"
FIELD_LAST_SYNC_AT = "last_sync_at"

_REDO_TRUTHY = frozenset({"1", "是", "yes", "y", "true", "redo", "重做"})


@dataclass(frozen=True)
class SheetRow:
    record_id: str
    url: str
    game_name: str
    redo: bool
    raw_fields: dict[str, Any]


@dataclass(frozen=True)
class RowDecision:
    record_id: str
    url: str
    game_name: str
    status: str  # queued | skipped_dup | skipped_dup_in_sheet | invalid
    reason: str = ""


def cell_text(value: Any) -> str:
    """Best-effort flatten Bitable cell values to a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        link = value.get("link") or value.get("Link") or ""
        text = value.get("text") or value.get("Text") or ""
        if link:
            return str(link).strip()
        if text:
            return str(text).strip()
        return ""
    if isinstance(value, list):
        parts = [cell_text(v) for v in value]
        return " ".join(p for p in parts if p).strip()
    return str(value).strip()


def normalize_url(raw: Any) -> str:
    return cell_text(raw)


def is_valid_http_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


def is_redo(value: Any) -> bool:
    text = cell_text(value).lower()
    return text in _REDO_TRUTHY


def parse_row(record: dict[str, Any]) -> SheetRow | None:
    """Return SheetRow or None if record_id missing."""
    record_id = str(record.get("record_id") or record.get("id") or "").strip()
    if not record_id:
        return None
    fields = record.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    return SheetRow(
        record_id=record_id,
        url=normalize_url(fields.get(FIELD_DOWNLOAD_URL)),
        game_name=cell_text(fields.get(FIELD_GAME_NAME)),
        redo=is_redo(fields.get(FIELD_REDO)),
        raw_fields=fields,
    )


def decide_row(
    row: SheetRow,
    *,
    seen: set[str],
    sheet_seen: set[str],
) -> RowDecision:
    if not row.url:
        return RowDecision(
            record_id=row.record_id,
            url="",
            game_name=row.game_name,
            status="invalid",
            reason="empty download_url",
        )
    if not is_valid_http_url(row.url):
        return RowDecision(
            record_id=row.record_id,
            url=row.url,
            game_name=row.game_name,
            status="invalid",
            reason="url must start with http:// or https://",
        )
    if row.url in sheet_seen:
        return RowDecision(
            record_id=row.record_id,
            url=row.url,
            game_name=row.game_name,
            status="skipped_dup_in_sheet",
            reason="duplicate row in sheet",
        )
    if row.url in seen and not row.redo:
        return RowDecision(
            record_id=row.record_id,
            url=row.url,
            game_name=row.game_name,
            status="skipped_dup",
            reason="already synced",
        )
    return RowDecision(
        record_id=row.record_id,
        url=row.url,
        game_name=row.game_name,
        status="queued",
    )
