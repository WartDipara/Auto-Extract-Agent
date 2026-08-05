from errors.builtin_sinks import register_builtin_sinks
from errors.mappers import register_builtin_mappers
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
    "setup_error_framework",
]


def setup_error_framework() -> None:
    """Explicit one-shot registration (mappers then sinks)."""
    register_builtin_mappers()
    register_builtin_sinks()


setup_error_framework()
