"""Error mapper router: register_mapper / normalize (dispatch)."""

from __future__ import annotations

import logging
from typing import Protocol

from errors.model import ErrorInfo
from errors.stage import current_stage

_log = logging.getLogger(__name__)

_MAPPERS: list[ErrorMapper] = []
_mappers_loaded = False


class ErrorMapper(Protocol):
    name: str

    def match(self, exc: BaseException) -> bool: ...

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo: ...


def register_mapper(mapper: ErrorMapper) -> None:
    _MAPPERS.append(mapper)
    _log.info("error mapper registered: %s", mapper.name)


def normalize(exc: BaseException, *, stage: str | None = None) -> ErrorInfo:
    _ensure_mappers()
    resolved_stage = stage if stage is not None else current_stage()
    for mapper in _MAPPERS:
        if mapper.match(exc):
            info = mapper.map(exc, stage=resolved_stage)
            _log.debug(
                "error normalized mapper=%s code=%s stage=%s",
                mapper.name,
                info.code,
                info.stage,
            )
            return info
    # Should not reach if UnexpectedMapper is registered last.
    return ErrorInfo(
        code="UNEXPECTED",
        message=str(exc) or type(exc).__name__,
        stage=resolved_stage,
        status="failed",
        cause_type=type(exc).__name__,
    )


def _ensure_mappers() -> None:
    global _mappers_loaded
    if _mappers_loaded:
        return
    _mappers_loaded = True
    from errors import mappers as _mappers  # noqa: F401
