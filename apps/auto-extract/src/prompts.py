"""
Load prompt templates from config/prompts.json (open for extension).
Business code fills slots; do not hardcode long prompts elsewhere.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import config

_log = logging.getLogger(__name__)
_CACHE: dict[str, Any] | None = None


def prompts_path() -> Path:
    return config.PROMPTS_FILE


def load_prompts(*, force_reload: bool = False) -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE
    path = prompts_path()
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"prompts.json root must be object: {path}")
    _CACHE = data
    return data


def get_template(dotted_key: str) -> str:
    """Resolve dotted key like 'opencode.initial' or 'opencode.resume.stall_continue'."""
    node: Any = load_prompts()
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"prompt key not found: {dotted_key} (missing {part!r})")
        node = node[part]
    if not isinstance(node, str) or not node.strip():
        raise KeyError(f"prompt key is not a non-empty string: {dotted_key}")
    return node


def render(dotted_key: str, **slots: Any) -> str:
    template = get_template(dotted_key)
    try:
        text = template.format(**slots)
    except KeyError as exc:
        raise KeyError(
            f"missing slot {exc} for prompt {dotted_key}"
        ) from exc
    record_prompt_history(dotted_key, text, slots)
    return text


def record_prompt_history(
    dotted_key: str,
    rendered: str,
    slots: dict[str, Any] | None = None,
) -> None:
    """Append emitted prompt for human review (state/prompts_history.jsonl)."""
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": dotted_key,
            "chars": len(rendered),
            "text": rendered,
        }
        if slots:
            # keep history readable; drop huge values if any
            payload["slots"] = {
                k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
                for k, v in slots.items()
            }
        with config.PROMPTS_HISTORY_FILE.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        _log.warning("cannot append prompts history: %s", exc)
