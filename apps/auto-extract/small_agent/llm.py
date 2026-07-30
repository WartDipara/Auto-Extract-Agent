"""Chat model factory via LangChain init_chat_model (multi-provider).

Routing (OCP: extend by MODEL_ID / BASE_URL, not by editing callers):
- BASE_URL set  → OpenAI-compatible endpoint (Minimax / GLM / DeepSeek / custom)
- else           → LangChain provider:model inference (openai:…, anthropic:…, deepseek:…)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from small_agent.config import SmallAgentSettings, llm_timeout_sec, load_settings

_log = logging.getLogger(__name__)


def _bare_model_id(model_id: str) -> str:
    """Strip provider prefix when forcing OpenAI-compatible transport."""
    if ":" not in model_id:
        return model_id
    provider, _, rest = model_id.partition(":")
    if provider and rest and "://" not in provider:
        return rest
    return model_id


def build_chat_model(settings: SmallAgentSettings | None = None) -> BaseChatModel:
    cfg = settings or load_settings()
    common: dict[str, Any] = {
        "temperature": 0,
        "timeout": llm_timeout_sec(),
        "api_key": cfg.api_key,
    }
    if cfg.base_url:
        model_name = _bare_model_id(cfg.model_id)
        _log.info(
            "small_agent llm openai-compatible model=%s base_url=%s",
            model_name,
            cfg.base_url,
        )
        print(
            f"small_agent llm provider=openai-compatible model={model_name}",
            flush=True,
        )
        return init_chat_model(
            model_name,
            model_provider="openai",
            base_url=cfg.base_url,
            **common,
        )

    _log.info("small_agent llm init_chat_model model=%s", cfg.model_id)
    print(f"small_agent llm model={cfg.model_id}", flush=True)
    return init_chat_model(cfg.model_id, **common)


# Backward-compatible alias used by agent / healthcheck.
def build_llm(settings: SmallAgentSettings | None = None) -> BaseChatModel:
    return build_chat_model(settings)
