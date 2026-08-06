from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence


@dataclass(frozen=True)
class IncomingChat:
    chat_id: str
    text: str
    sender_id: str = ""
    sender_name: str = ""


MessageHandler = Callable[[IncomingChat], None]


class Channel(Protocol):
    def start(self, on_message: MessageHandler) -> None: ...

    def stop(self) -> None: ...

    def reply_text(
        self,
        chat_id: str,
        text: str,
        *,
        at_user_ids: Sequence[str] | None = None,
    ) -> None: ...

    def send_file(self, chat_id: str, path: Path) -> None: ...
