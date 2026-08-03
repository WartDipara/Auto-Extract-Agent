"""Extensible task error framework: TaskError, stage_scope, normalize, emit."""

from errors.model import ErrorInfo, TaskError
from errors.router import normalize, register_mapper
from errors.sinks import emit, register_sink
from errors.stage import current_stage, stage_scope

__all__ = [
    "ErrorInfo",
    "TaskError",
    "current_stage",
    "stage_scope",
    "register_mapper",
    "normalize",
    "register_sink",
    "emit",
]
