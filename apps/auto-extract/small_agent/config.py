from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

_APP_ROOT = Path(__file__).resolve().parent.parent
_DOTENV = _APP_ROOT / ".env"
_loaded = False
_DEFAULT_MODEL = "deepseek-v4-flash"
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


def load_settings() -> SmallAgentSettings:
    ensure_dotenv()
    return SmallAgentSettings(
        api_key=(os.getenv("DEEPSEEK_API_KEY") or "").strip(),
        model_id=(os.getenv("SMALL_AGENT_MODEL_ID") or _DEFAULT_MODEL).strip(),
    )


def build_llm_kwargs(settings: SmallAgentSettings) -> dict:
    return {
        "model": settings.model_id,
        "api_key": settings.api_key,
        "temperature": 0,
        "timeout": _TIMEOUT_SEC,
    }
