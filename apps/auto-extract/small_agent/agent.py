from __future__ import annotations
import logging
import uuid
from typing import Any
from langchain.agents import create_agent
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import InMemorySaver
from small_agent.config import SmallAgentSettings, load_settings
from small_agent.prompts import (
    SYSTEM_PROMPT,
    TASK_BOOTSTRAP,
    format_ocr_user_message,
)
from small_agent.tools import FrameOutcome, FrameSession, TapDevice, build_tools

_log = logging.getLogger(__name__)


def build_llm(settings: SmallAgentSettings | None = None) -> ChatDeepSeek:
    from small_agent.config import build_llm_kwargs

    cfg = settings or load_settings()
    return ChatDeepSeek(**build_llm_kwargs(cfg))


class UiAgentSession:
    def __init__(
        self,
        adb: TapDevice,
        *,
        thread_id: str | None = None,
        settings: SmallAgentSettings | None = None,
        llm: ChatDeepSeek | None = None,
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
        self._invoke_config = {"configurable": {"thread_id": self._thread_id}}
        self._bootstrapped = False
        if agent is not None:
            self._agent = agent
        else:
            model = llm or build_llm(self._settings)
            self._agent = create_agent(
                model=model,
                tools=build_tools(self._frame),
                system_prompt=SYSTEM_PROMPT,
                checkpointer=InMemorySaver(),
            )

    @property
    def thread_id(self) -> str:
        return self._thread_id

    def bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._agent.invoke(
            {"messages": [{"role": "user", "content": TASK_BOOTSTRAP}]},
            self._invoke_config,
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
        self._frame.set_items(items)
        content = format_ocr_user_message(items, poll=poll, note=note)
        try:
            self._agent.invoke(
                {"messages": [{"role": "user", "content": content}]},
                self._invoke_config,
            )
        except Exception as exc:
            _log.warning("small_agent decide failed: %s", exc)
            print(f"small_agent decide error: {exc}", flush=True)
            return FrameOutcome(kind="wait")
        outcome = self._frame.outcome
        if outcome is None:
            return FrameOutcome(kind="wait")
        return outcome
