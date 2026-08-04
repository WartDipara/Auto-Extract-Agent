from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

MessageHandler = Callable[[str, str], None]


class Channel(Protocol):
    def start(self, on_message: MessageHandler) -> None: ...

    def stop(self) -> None: ...

    def reply_text(self, chat_id: str, text: str) -> None: ...

    def send_file(self, chat_id: str, path: Path) -> None: ...
