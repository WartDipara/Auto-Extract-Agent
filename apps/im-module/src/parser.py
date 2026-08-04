from __future__ import annotations

import json
import re
from typing import Any

_CODE_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TRAIL_PUNCT = ".,;:)]}>\"'"


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = _CODE_FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def validate_get_texts(payload: dict[str, Any]) -> list[str] | None:
    """Return cleaned urls or None if invalid."""
    body = payload.get("get-texts")
    if not isinstance(body, dict):
        return None
    urls = body.get("urls")
    if not isinstance(urls, list) or not urls:
        return None
    cleaned = [str(u).strip() for u in urls if str(u).strip()]
    return cleaned or None


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs; strip trailing punctuation; dedupe preserving order."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(_TRAIL_PUNCT)
        if not url or url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def parse_task_message(text: str) -> dict[str, Any] | None:
    """Return inbox root object or None.

    Prefer legacy get-texts JSON; otherwise accept bare pasted URL(s).
    """
    data = extract_json_object(text)
    if data is not None:
        urls = validate_get_texts(data)
        if urls is not None:
            return {"get-texts": {"urls": urls}}
    urls = extract_urls(text)
    if not urls:
        return None
    return {"get-texts": {"urls": urls}}
