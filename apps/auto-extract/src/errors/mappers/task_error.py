from __future__ import annotations

from errors.model import ErrorInfo, TaskError


class TaskErrorMapper:
    name = "task_error"

    def match(self, exc: BaseException) -> bool:
        return isinstance(exc, TaskError)

    def map(self, exc: BaseException, *, stage: str) -> ErrorInfo:
        assert isinstance(exc, TaskError)
        return exc.to_info(stage=stage)
