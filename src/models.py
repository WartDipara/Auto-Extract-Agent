from dataclasses import dataclass, field


STATUSES = (
    "queued",
    "downloading",
    "downloaded",
    "submitting",
    "waiting_csv",
    "success",
    "decrypt_failed",
    "failed",
    "timeout",
)


@dataclass
class Task:
    task_id: str
    url: str
    source_file: str = ""
    filename: str = ""
    status: str = "queued"
    error: str = ""
    result_csv: str = ""
    session_id: str = ""


@dataclass
class QueueState:
    next_seq: int = 1
    tasks: list = field(default_factory=list)
