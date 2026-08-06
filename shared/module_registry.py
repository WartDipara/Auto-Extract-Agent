from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

SHARED_TASKS_DB = (_REPO_ROOT / "apps" / "auto-extract" / "state" / "tasks.db").resolve()

GET_TEXTS_MODULE_ID = "get-texts"

_GET_TEXTS_ACTIVE = frozenset(
    {
        "queued",
        "downloaded",
        "patched",
        "on_device",
        "device_done",
        "on_extract",
        "extract_done",
    }
)
_GET_TEXTS_TERMINAL = frozenset(
    {
        "success",
        "decrypt_failed",
        "assets_missing",
        "abnormal_exit",
        "failed",
        "timeout",
    }
)


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    app_root: Path
    inbox_dir: Path
    workspace_root: Path
    downloads_dir: Path
    result_dir: Path
    buf_done_dir: Path
    state_dir: Path
    heartbeat_path: Path
    tasks_table: str
    meta_seq_key: str
    inbox_route: str
    active_statuses: frozenset[str]
    terminal_statuses: frozenset[str]


def _get_texts_spec() -> ModuleSpec:
    app = (_REPO_ROOT / "apps" / "auto-extract").resolve()
    state = app / "state"
    return ModuleSpec(
        module_id=GET_TEXTS_MODULE_ID,
        app_root=app,
        inbox_dir=(app / "inbox").resolve(),
        workspace_root=(app / "workspace").resolve(),
        downloads_dir=(app / "downloads").resolve(),
        result_dir=(app / "result").resolve(),
        buf_done_dir=(app / "buf_done").resolve(),
        state_dir=state.resolve(),
        heartbeat_path=(state / "heartbeat").resolve(),
        tasks_table="tasks",
        meta_seq_key="next_seq",
        inbox_route="get-texts",
        active_statuses=_GET_TEXTS_ACTIVE,
        terminal_statuses=_GET_TEXTS_TERMINAL,
    )


_REGISTRY: tuple[ModuleSpec, ...] = (_get_texts_spec(),)


def all_modules() -> tuple[ModuleSpec, ...]:
    return _REGISTRY


def get_module(module_id: str) -> ModuleSpec:
    for spec in _REGISTRY:
        if spec.module_id == module_id:
            return spec
    raise KeyError(f"unknown module_id: {module_id}")


def primary_module() -> ModuleSpec:
    return get_module(GET_TEXTS_MODULE_ID)
