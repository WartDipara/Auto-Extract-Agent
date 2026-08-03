from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_STAGE: ContextVar[str] = ContextVar("task_error_stage", default="")


def current_stage() -> str:
    return _STAGE.get()


@contextmanager
def stage_scope(name: str) -> Iterator[None]:
    """Push a free-form stage name for the duration of the block."""
    token = _STAGE.set(name or "")
    try:
        yield
    finally:
        _STAGE.reset(token)
