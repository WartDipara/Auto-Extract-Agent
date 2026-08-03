from __future__ import annotations

from errors.model import ErrorInfo


class UnexpectedMapper:
    """Always matches; must be registered last."""

    name = "unexpected"

    def match(self, exc: BaseException) -> bool:
        return True

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo:
        return ErrorInfo(
            code="UNEXPECTED",
            message=str(exc) or type(exc).__name__,
            stage=stage,
            status="failed",
            cause_type=type(exc).__name__,
        )
