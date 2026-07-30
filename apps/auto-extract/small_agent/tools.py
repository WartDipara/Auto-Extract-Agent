from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol
from langchain_core.tools import tool

_VALID_SCENES = frozenset({"login", "start_game", "server_select", "entry"})


class TapDevice(Protocol):
    def tap(self, x: int, y: int) -> None: ...


@dataclass
class FrameOutcome:
    kind: str  # tap | wait | done
    scene: str = ""
    item_id: int | None = None
    text: str = ""


@dataclass
class FrameSession:
    adb: TapDevice
    items: list[Any] = field(default_factory=list)
    outcome: FrameOutcome | None = None

    def set_items(self, items: list[Any]) -> None:
        self.items = list(items)
        self.outcome = None


def build_tools(session: FrameSession) -> list[Any]:
    def _already_done() -> str | None:
        if session.outcome is None:
            return None
        return (
            f"already decided this frame as {session.outcome.kind}; "
            "do not call more tools"
        )

    @tool
    def tap_item(item_id: int) -> str:
        """Tap the OCR item center by id from the current frame list."""
        blocked = _already_done()
        if blocked:
            return blocked
        if item_id < 0 or item_id >= len(session.items):
            return f"invalid item_id={item_id}; call wait instead"
        item = session.items[item_id]
        session.adb.tap(item.cx, item.cy)
        session.outcome = FrameOutcome(
            kind="tap",
            item_id=item_id,
            text=getattr(item, "text", "") or "",
        )
        return (
            f"tapped id={item_id} text={getattr(item, 'text', '')!r} "
            f"at ({item.cx},{item.cy})"
        )

    @tool
    def wait() -> str:
        """Do not tap; wait for download progress or clearer UI."""
        blocked = _already_done()
        if blocked:
            return blocked
        session.outcome = FrameOutcome(kind="wait")
        return "waiting"

    @tool
    def done(scene: str) -> str:
        """Entry screen reached. scene: login | start_game | server_select | entry."""
        blocked = _already_done()
        if blocked:
            return blocked
        scene_key = (scene or "").strip().lower()
        if scene_key not in _VALID_SCENES:
            scene_key = "entry"
        session.outcome = FrameOutcome(kind="done", scene=scene_key)
        return f"done scene={scene_key}"

    return [tap_item, wait, done]
