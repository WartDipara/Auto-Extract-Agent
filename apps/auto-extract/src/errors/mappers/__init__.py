from errors.mappers.opencode_stopped import OpenCodeStoppedMapper
from errors.mappers.task_error import TaskErrorMapper
from errors.mappers.timeout import TimeoutMapper
from errors.mappers.unexpected import UnexpectedMapper
from errors.router import register_mapper

_registered = False


def register_builtin_mappers() -> None:
    global _registered
    if _registered:
        return
    register_mapper(TaskErrorMapper())
    register_mapper(TimeoutMapper())
    register_mapper(OpenCodeStoppedMapper())
    register_mapper(UnexpectedMapper())
    _registered = True
