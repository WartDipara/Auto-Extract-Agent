from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent
_DOTENV = _APP_ROOT / ".env"
_loaded = False
_DEFAULT_MODEL = "deepseek:deepseek-chat"
_TIMEOUT_SEC = 30.0


def ensure_dotenv() -> None:
    global _loaded
    if not _loaded:
        load_dotenv(_DOTENV)
        _loaded = True


@dataclass(frozen=True)
class SmallAgentSettings:
    api_key: str
    model_id: str
    base_url: str | None


def load_settings() -> SmallAgentSettings:
    ensure_dotenv()
    return SmallAgentSettings(
        api_key=(os.getenv("API_KEY") or "").strip(),
        model_id=(os.getenv("MODEL_ID") or _DEFAULT_MODEL).strip(),
        base_url=(os.getenv("BASE_URL") or "").strip() or None,
    )


def llm_timeout_sec() -> float:
    return _TIMEOUT_SEC
