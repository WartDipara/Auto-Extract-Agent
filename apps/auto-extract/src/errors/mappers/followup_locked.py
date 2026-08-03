from __future__ import annotations

from errors.model import ErrorInfo


class FollowupLockedMapper:
    name = "followup_locked"

    def match(self, exc: BaseException) -> bool:
        try:
            from shared.archive_contract import FollowupLockedError
        except ImportError:
            return False
        return isinstance(exc, FollowupLockedError)

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo:
        return ErrorInfo(
            code="WORKSPACE_LOCKED",
            message=str(exc) or "followup locked",
            stage=stage or "prepare",
            status="failed",
            cause_type=type(exc).__name__,
        )
