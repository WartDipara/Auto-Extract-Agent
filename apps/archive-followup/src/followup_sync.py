"""After follow-up: filter tests.csv and sync result CSV; update meta."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from shared.archive_contract import (
    OPENCODE_OUTPUT_NAME,
    default_result_csv_path,
    utc_now,
    write_meta,
)
from shared.sensitive_words import filter_sensitive_file

_log = logging.getLogger(__name__)


def sync_result(
    *,
    task_root: Path,
    result_dir: Path,
    meta: dict[str, Any],
) -> Path | None:
    tests_csv = Path(task_root) / "outputs" / OPENCODE_OUTPUT_NAME
    if not tests_csv.is_file() or not tests_csv.read_text(
        encoding="utf-8-sig", errors="replace"
    ).strip():
        print("no non-empty outputs/tests.csv; skip result sync", flush=True)
        return None

    removed = filter_sensitive_file(tests_csv)
    if removed:
        print(f"sensitive filter removed {removed} lines", flush=True)

    body = tests_csv.read_text(encoding="utf-8-sig", errors="replace")
    if not body.strip():
        print("tests.csv empty after sensitive filter; skip result sync", flush=True)
        return None

    task_key = str(meta.get("task_key") or Path(task_root).name)
    label = str(meta.get("label") or "")
    result_csv = str(meta.get("result_csv") or "").strip()
    dest = Path(result_csv) if result_csv else default_result_csv_path(
        result_dir, task_key, label
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8-sig")
    print(f"result csv updated: {dest}", flush=True)

    updated = dict(meta)
    updated["task_key"] = task_key
    updated["result_csv"] = str(dest.resolve())
    updated["finished_at"] = utc_now()
    updated["followup"] = True
    write_meta(task_root, updated)
    _log.info("followup synced result=%s task=%s", dest, task_key)
    return dest
