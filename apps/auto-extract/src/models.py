from dataclasses import dataclass, field

from shared.module_registry import GET_TEXTS_MODULE_ID, get_module

_MODULE = get_module(GET_TEXTS_MODULE_ID)

TERMINAL_STATUSES = _MODULE.terminal_statuses
ACTIVE_STATUSES = _MODULE.active_statuses


@dataclass
class Task:
    task_id: str
    url: str
    source_file: str = ""
    filename: str = ""
    labels: dict = field(default_factory=dict)
    label: str = ""
    status: str = "queued"
    error: str = ""
    result_csv: str = ""
    session_id: str = ""
    buf_done_zip: str = ""
    adb_serial: str = ""
    # Prep soft outcomes: missing hotfix must not fail the task.
    hotfix_has_files: str = ""  # "yes" | "no" | ""
    hotfix_pull_source: str = ""
    screen_reached: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    im_delivered_at: str = ""
    im_chat_id: str = ""
    im_sender_id: str = ""
    im_deliver_error: str = ""


@dataclass
class QueueState:
    next_seq: int = 1
