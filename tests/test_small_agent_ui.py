"""Unit tests for prep foreground watch + small_agent (mocked LLM)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_APP = _REPO / "apps" / "auto-extract"
_SRC = _APP / "src"
for p in (_APP, _SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@dataclass
class FakeOcr:
    text: str
    cx: int
    cy: int


class FakeAdb:
    def __init__(self):
        self.taps: list[tuple[int, int]] = []
        self.running = True
        self.focused = "com.demo.game"
        self.launches = 0

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def is_package_running(self, package: str) -> bool:
        return self.running

    def foreground_package(self) -> str:
        return self.focused

    def bring_to_foreground(self, package: str) -> None:
        self.launches += 1
        self.focused = package

    def launch_package(self, package: str) -> None:
        self.bring_to_foreground(package)


def test_foreground_watch_apply():
    from shared.prep.foreground_watch import ForegroundState, ForegroundWatch

    adb = FakeAdb()
    watch = ForegroundWatch(adb, "com.demo.game", poll_sec=0.1)

    assert watch.classify() is ForegroundState.FOREGROUND
    assert watch.apply(ForegroundState.FOREGROUND) is None

    adb.focused = "com.android.chrome"
    assert watch.classify() is ForegroundState.BACKGROUNDED
    assert watch.apply(ForegroundState.BACKGROUNDED) == "brought_back"
    assert adb.launches == 1
    assert adb.focused == "com.demo.game"

    adb.running = False
    assert watch.classify() is ForegroundState.CRASHED
    assert watch.apply(ForegroundState.CRASHED) == "crash"
    print("FOREGROUND_WATCH_OK", flush=True)


def test_ocr_worth_decide():
    from small_agent.agent import ocr_worth_decide

    assert not ocr_worth_decide([])
    assert not ocr_worth_decide([FakeOcr("/", 1, 1), FakeOcr("AG", 2, 2)])
    assert ocr_worth_decide([FakeOcr("同意并进入", 10, 20)])
    assert ocr_worth_decide([FakeOcr("Login", 10, 20)])
    print("OCR_WORTH_DECIDE_OK", flush=True)


def test_tools_one_shot_lock():
    from small_agent.tools import FrameSession, build_tools

    adb = FakeAdb()
    session = FrameSession(adb=adb)
    session.set_items([FakeOcr("同意", 100, 200)])
    tools = {t.name: t for t in build_tools(session)}
    tools["tap_item"].invoke({"item_id": 0})
    second = tools["wait"].invoke({})
    assert "already decided" in second
    assert session.outcome is not None and session.outcome.kind == "tap"
    assert len(adb.taps) == 1
    print("SMALL_AGENT_TOOL_LOCK_OK", flush=True)


def test_tools_tap_wait_done():
    from small_agent.tools import FrameSession, build_tools

    adb = FakeAdb()
    session = FrameSession(adb=adb)
    session.set_items([FakeOcr("同意", 100, 200), FakeOcr("登录", 50, 50)])
    tools = {t.name: t for t in build_tools(session)}

    assert tools["tap_item"].invoke({"item_id": 0}).startswith("tapped")
    assert session.outcome is not None and session.outcome.kind == "tap"
    assert adb.taps == [(100, 200)]

    session.set_items([FakeOcr("下载中", 1, 1)])
    assert tools["wait"].invoke({}) == "waiting"
    assert session.outcome is not None and session.outcome.kind == "wait"

    session.set_items([FakeOcr("登录", 1, 1)])
    assert tools["done"].invoke({"scene": "login"}).endswith("login")
    assert session.outcome is not None
    assert session.outcome.kind == "done"
    assert session.outcome.scene == "login"
    print("SMALL_AGENT_TOOLS_OK", flush=True)


def test_llm_routing_helpers():
    from small_agent.llm import _bare_model_id

    assert _bare_model_id("deepseek:deepseek-v4-flash") == "deepseek-v4-flash"
    assert _bare_model_id("openai:gpt-4o-mini") == "gpt-4o-mini"
    assert _bare_model_id("MiniMax-Text-01") == "MiniMax-Text-01"
    print("SMALL_AGENT_LLM_ROUTE_OK", flush=True)


def test_ping_without_key():
    import small_agent.config as cfg
    import small_agent.healthcheck as hc
    from small_agent.config import SmallAgentSettings

    cfg._loaded = True
    previous = cfg.load_settings

    def _no_key() -> SmallAgentSettings:
        return SmallAgentSettings(
            api_key="",
            model_id="deepseek:deepseek-chat",
            base_url=None,
        )

    cfg.load_settings = _no_key  # type: ignore[assignment]
    try:
        assert hc.ping_model() is False
    finally:
        cfg.load_settings = previous  # type: ignore[assignment]
    print("SMALL_AGENT_PING_NO_KEY_OK", flush=True)


def test_ping_ok_reply():
    import small_agent.healthcheck as hc

    class FakeLLM:
        def invoke(self, prompt):
            return SimpleNamespace(content="pong")

    assert hc.ping_model(FakeLLM()) is True  # type: ignore[arg-type]
    print("SMALL_AGENT_PING_OK", flush=True)


def test_ui_agent_decide_with_fake_agent():
    from small_agent.agent import UiAgentSession
    from small_agent.tools import FrameOutcome

    adb = FakeAdb()
    calls: list[str] = []
    holder: dict = {}

    class ToolingAgent:
        def invoke(self, payload, config=None):
            content = payload["messages"][0]["content"]
            calls.append(content)
            if "poll=" in content:
                holder["s"]._frame.outcome = FrameOutcome(kind="done", scene="login")
            return {}

    session = UiAgentSession(adb, thread_id="test-thread", agent=ToolingAgent())
    holder["s"] = session
    session.bootstrap()
    assert any("工作说明" in c for c in calls)

    out = session.decide([FakeOcr("登录", 1, 2)], poll=1)
    assert out.kind == "done"
    assert out.scene == "login"
    print("SMALL_AGENT_DECIDE_OK", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_foreground_watch_apply()
    test_ocr_worth_decide()
    test_tools_one_shot_lock()
    test_tools_tap_wait_done()
    test_llm_routing_helpers()
    test_ping_without_key()
    test_ping_ok_reply()
    test_ui_agent_decide_with_fake_agent()
