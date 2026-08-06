from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_lock = threading.Lock()


def _quarantine_corrupt(path: Path, exc: Exception) -> None:
    stamp = int(time.time())
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        shutil.copy2(path, backup)
        path.unlink(missing_ok=True)
    except OSError:
        _log.exception("pending inbox quarantine failed path=%s", path)
        raise RuntimeError(f"pending inbox corrupt and unreadable: {path}") from exc
    _log.error(
        "pending inbox corrupt; quarantined to %s (%s). starting empty ledger",
        backup,
        exc,
    )


def _load(path: Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _quarantine_corrupt(target, exc)
        return []
    except OSError as exc:
        _log.exception("pending inbox read failed path=%s", target)
        raise RuntimeError(f"pending inbox unreadable: {target}") from exc
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [x for x in data["items"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    _log.error("pending inbox invalid shape path=%s; quarantining", target)
    _quarantine_corrupt(target, ValueError("invalid pending inbox shape"))
    return []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": items}
    tmp = target.with_suffix(target.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    # Refuse to replace a still-corrupt live file that appeared mid-flight.
    if target.is_file():
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"pending inbox became corrupt before save: {target}"
            ) from exc
    tmp.replace(target)


def list_pending(path: Path) -> list[dict[str, Any]]:
    with _lock:
        return list(_load(path))


def add_pending(
    path: Path,
    *,
    filename: str,
    inbox_path: str,
    chat_id: str,
    sender_id: str,
    urls: list[str],
    route: str,
) -> None:
    name = (filename or "").strip()
    if not name:
        return
    item = {
        "filename": name,
        "inbox_path": str(inbox_path),
        "chat_id": (chat_id or "").strip(),
        "sender_id": (sender_id or "").strip(),
        "urls": list(urls),
        "route": (route or "").strip() or "get-texts",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resubmit_count": 0,
    }
    with _lock:
        items = _load(path)
        items = [x for x in items if str(x.get("filename") or "") != name]
        items.append(item)
        _save(path, items)
        _log.info("pending inbox tracked file=%s", name)


def remove_pending(path: Path, filename: str) -> bool:
    name = (filename or "").strip()
    if not name:
        return False
    with _lock:
        items = _load(path)
        kept = [x for x in items if str(x.get("filename") or "") != name]
        if len(kept) == len(items):
            return False
        _save(path, kept)
        _log.info("pending inbox cleared file=%s", name)
        return True


def bump_resubmit(path: Path, filename: str) -> int:
    name = (filename or "").strip()
    with _lock:
        items = _load(path)
        count = 0
        for item in items:
            if str(item.get("filename") or "") == name:
                count = int(item.get("resubmit_count") or 0) + 1
                item["resubmit_count"] = count
                item["last_resubmit_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                break
        _save(path, items)
        return count


def mark_exhausted(path: Path, filename: str) -> None:
    name = (filename or "").strip()
    with _lock:
        items = _load(path)
        for item in items:
            if str(item.get("filename") or "") == name:
                item["exhausted"] = True
                item["exhausted_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                break
        _save(path, items)
