"""Channel protocol — Feishu today, DingTalk later without touching courier."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol


# (chat_id, text) — keep handler under 3s for Feishu WS.
MessageHandler = Callable[[str, str], None]


class Channel(Protocol):
    def start(self, on_message: MessageHandler) -> None:
        """Block and dispatch inbound messages."""

    def reply_text(self, chat_id: str, text: str) -> None: ...

    def send_file(self, chat_id: str, path: Path) -> None: ...
