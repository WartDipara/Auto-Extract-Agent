from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ErrorInfo:
    code: str
    message: str
    stage: str = ""
    status: str = "failed"
    details: dict[str, Any] = field(default_factory=dict)
    cause_type: str = ""

    def to_line(self) -> str:
        where = f"{self.code}@{self.stage}" if self.stage else self.code
        msg = (self.message or "").strip()
        return f"[{where}] {msg}" if msg else f"[{where}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
            "cause_type": self.cause_type,
        }


class TaskError(Exception):
    """Business error with stable code; stage may come from stage_scope."""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        stage: str | None = None,
        status: str = "failed",
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ):
        self.code = code
        self.message = message or code
        self.stage = stage
        self.status = status
        self.details = dict(details or {})
        self.cause = cause
        super().__init__(self.message)

    def to_info(self, *, stage: str = "") -> ErrorInfo:
        return ErrorInfo(
            code=self.code,
            message=self.message,
            stage=self.stage if self.stage is not None else stage,
            status=self.status,
            details=dict(self.details),
            cause_type=type(self.cause).__name__ if self.cause else type(self).__name__,
        )
