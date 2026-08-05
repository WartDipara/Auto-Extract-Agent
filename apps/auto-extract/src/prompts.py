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
    _log.info("prompt rendered key=%s chars=%s", dotted_key, len(text))
    return text
