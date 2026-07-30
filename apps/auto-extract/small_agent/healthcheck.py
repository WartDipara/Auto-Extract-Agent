"""Connectivity probe before OCR navigation."""

from __future__ import annotations

import logging
import re

from langchain_core.language_models.chat_models import BaseChatModel

from small_agent.config import load_settings
from small_agent.prompts import PING_PROMPT

_log = logging.getLogger(__name__)
_OK_RE = re.compile(r"\b(OK|pong)\b", re.IGNORECASE)


def ping_model(llm: BaseChatModel | None = None) -> bool:
    """Return True if model replies with OK or pong."""
    if llm is None:
        settings = load_settings()
        if not settings.api_key:
            _log.error("API_KEY missing in .env")
            print("small_agent ping failed: no API_KEY", flush=True)
            return False
        from small_agent.llm import build_chat_model

        model = build_chat_model(settings)
    else:
        model = llm
    try:
        msg = model.invoke(PING_PROMPT)
    except Exception as exc:
        _log.error("small_agent ping error: %s", exc)
        print(f"small_agent ping error: {exc}", flush=True)
        return False
    text = getattr(msg, "content", None) or str(msg)
    if isinstance(text, list):
        text = " ".join(str(part) for part in text)
    text = str(text).strip()
    ok = bool(_OK_RE.search(text))
    print(f"small_agent ping -> {text!r} ok={ok}", flush=True)
    return ok
