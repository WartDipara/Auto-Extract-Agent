from __future__ import annotations

from errors.model import ErrorInfo


class TimeoutMapper:
    name = "timeout"

    def match(self, exc: BaseException) -> bool:
        return isinstance(exc, TimeoutError)

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo:
        return ErrorInfo(
            code="EXTRACT_TIMEOUT",
            message=str(exc) or "timeout",
            stage=stage or "extract",
            status="timeout",
            cause_type=type(exc).__name__,
        )
