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
    @tool
    def tap_item(item_id: int) -> str:
        """Tap the OCR item center by id from the current frame list."""
        if item_id < 0 or item_id >= len(session.items):
            return f"invalid item_id={item_id}; valid 0..{len(session.items) - 1}"
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
        session.outcome = FrameOutcome(kind="wait")
        return "waiting"

    @tool
    def done(scene: str) -> str:
        """Entry screen reached. scene: login | start_game | server_select | entry."""
        scene_key = (scene or "").strip().lower()
        if scene_key not in _VALID_SCENES:
            scene_key = "entry"
        session.outcome = FrameOutcome(kind="done", scene=scene_key)
        return f"done scene={scene_key}"

    return [tap_item, wait, done]
