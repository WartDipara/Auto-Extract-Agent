"""UI agent with InMemorySaver. One tool decision per OCR frame."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from small_agent.config import SmallAgentSettings, load_settings
from small_agent.llm import build_chat_model
from small_agent.prompts import (
    SYSTEM_PROMPT,
    TASK_BOOTSTRAP,
    format_ocr_user_message,
)
from small_agent.tools import FrameOutcome, FrameSession, TapDevice, build_tools

_log = logging.getLogger(__name__)

_BOOTSTRAP_RECURSION = 4
_DECIDE_RECURSION = 4


def ocr_worth_decide(items: list[Any]) -> bool:
    """Skip LLM on splash crumbs (e.g. '/' / 'AG') with no real UI text."""
    for item in items:
        text = (getattr(item, "text", "") or "").strip()
        if any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return True
        if len(text) >= 4:
            return True
    return False


class UiAgentSession:
    def __init__(
        self,
        adb: TapDevice,
        *,
        thread_id: str | None = None,
        settings: SmallAgentSettings | None = None,
        llm: BaseChatModel | None = None,
        agent: Any | None = None,
    ):
        if settings is not None:
            self._settings = settings
        elif agent is None:
            self._settings = load_settings()
        else:
            self._settings = None
        self._frame = FrameSession(adb=adb)
        self._thread_id = thread_id or f"prep-{uuid.uuid4().hex[:12]}"
        self._bootstrapped = False
        if agent is not None:
            self._agent = agent
        else:
            model = llm or build_chat_model(self._settings)
            self._agent = create_agent(
                model=model,
                tools=build_tools(self._frame),
                system_prompt=SYSTEM_PROMPT,
                checkpointer=InMemorySaver(),
            )

    @property
    def thread_id(self) -> str:
        return self._thread_id

    def _config(self, recursion_limit: int) -> dict:
        return {
            "configurable": {"thread_id": self._thread_id},
            "recursion_limit": recursion_limit,
        }

    def bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._agent.invoke(
            {"messages": [{"role": "user", "content": TASK_BOOTSTRAP}]},
            self._config(_BOOTSTRAP_RECURSION),
        )
        self._bootstrapped = True
        print("small_agent bootstrap done", flush=True)

    def decide(
        self,
        items: list[Any],
        *,
        poll: int,
        note: str = "",
    ) -> FrameOutcome:
        if not ocr_worth_decide(items):
            print(f"ocr gate skip llm (sparse ocr) poll={poll}", flush=True)
            return FrameOutcome(kind="wait")

        self._frame.set_items(items)
        content = format_ocr_user_message(items, poll=poll, note=note)
        try:
            self._agent.invoke(
                {"messages": [{"role": "user", "content": content}]},
                self._config(_DECIDE_RECURSION),
            )
        except GraphRecursionError:
            _log.warning("small_agent decide hit recursion_limit poll=%s", poll)
            print("small_agent decide: recursion_limit (using last tool)", flush=True)
        except Exception as exc:
            _log.warning("small_agent decide failed: %s", exc)
            print(f"small_agent decide error: {exc}", flush=True)
            return FrameOutcome(kind="wait")
        outcome = self._frame.outcome
        if outcome is None:
            return FrameOutcome(kind="wait")
        return outcome
