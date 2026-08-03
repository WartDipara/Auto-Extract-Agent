"""Register built-in mappers in match order (first match wins; unexpected last)."""

from errors.mappers.followup_locked import FollowupLockedMapper
from errors.mappers.opencode_stopped import OpenCodeStoppedMapper
from errors.mappers.task_error import TaskErrorMapper
from errors.mappers.timeout import TimeoutMapper
from errors.mappers.unexpected import UnexpectedMapper
from errors.router import register_mapper

register_mapper(TaskErrorMapper())
register_mapper(TimeoutMapper())
register_mapper(OpenCodeStoppedMapper())
register_mapper(FollowupLockedMapper())
register_mapper(UnexpectedMapper())
