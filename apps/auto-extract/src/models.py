from dataclasses import dataclass, field


STATUSES = (
    "queued",
    "downloaded",
    "patched",
    "on_device",
    "device_done",
    "on_extract",
    "extract_done",
    "success",
    "decrypt_failed",
    "assets_missing",
    "abnormal_exit",
    "failed",
    "timeout",
)

TERMINAL_STATUSES = frozenset(
    {
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)

ACTIVE_STATUSES = frozenset(s for s in STATUSES if s not in TERMINAL_STATUSES)


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
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    im_delivered_at: str = ""


@dataclass
class QueueState:
    next_seq: int = 1
