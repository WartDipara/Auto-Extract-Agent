from dataclasses import dataclass, field


STATUSES = (
    "queued",
    "downloading",
    "downloaded",
    "preparing",
    "submitting",
    "waiting_csv",
    "success",
    "decrypt_failed",
    "assets_missing",
    "abnormal_exit",
    "failed",
    "timeout",
)


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


@dataclass
class QueueState:
    next_seq: int = 1
    tasks: list = field(default_factory=list)
