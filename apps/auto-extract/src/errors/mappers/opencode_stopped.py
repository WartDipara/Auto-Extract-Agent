from __future__ import annotations

from errors.model import ErrorInfo


class OpenCodeStoppedMapper:
    name = "opencode_stopped"

    def match(self, exc: BaseException) -> bool:
        try:
            from opencode_session import OpenCodeStopped
        except ImportError:
            return False
        return isinstance(exc, OpenCodeStopped)

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo:
        return ErrorInfo(
            code="EXTRACT_STOPPED",
            message=str(exc) or "opencode stopped",
            stage=stage or "extract",
            status="failed",
            cause_type=type(exc).__name__,
        )
