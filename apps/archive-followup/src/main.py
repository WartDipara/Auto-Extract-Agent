"""
Archive follow-up module (B): list task workspaces, or resume OpenCode in-place.

Does not import apps.auto-extract business code — only shared.archive_contract
and the auto-extract disk layout.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_REPO = _SRC.parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shared.archive_contract import (  # noqa: E402
    CONTRACT_VERSION,
    acquire_followup_lock,
    auto_extract_paths,
    find_task_root_by_session,
    has_followup_lock,
    has_module_a_done,
    iter_task_workspaces,
    read_meta,
    release_followup_lock,
    task_workspace,
)

from followup_sync import sync_result  # noqa: E402
from opencode_resume import resume_opencode  # noqa: E402


def print_index() -> None:
    paths = auto_extract_paths(_REPO)
    root = paths["workspace"]
    print(f"archive-followup | contract={CONTRACT_VERSION}")
    print(f"workspace: {root}")
    rows = list(iter_task_workspaces(root))
    print(f"tasks: {len(rows)}")
    for key, task_root in rows:
        meta = read_meta(task_root) or {}
        sid = meta.get("session_id") or "-"
        st = meta.get("status") or "-"
        label = meta.get("label") or "-"
        done = "a_done" if has_module_a_done(task_root) else "no_a_done"
        flock = " followup_lock" if has_followup_lock(task_root) else ""
        print(f"  {key} session={sid} status={st} label={label} {done}{flock}")
    print("ARCHIVE_FOLLOWUP_OK")


def run_followup(*, session_id: str = "", task_key: str = "", prompt: str) -> int:
    paths = auto_extract_paths(_REPO)
    workspace_root = paths["workspace"]

    if task_key:
        task_root = task_workspace(workspace_root, task_key)
        if not task_root.is_dir():
            raise SystemExit(f"task workspace not found: {task_key}")
    elif session_id:
        task_root = find_task_root_by_session(workspace_root, session_id)
        if task_root is None:
            raise SystemExit(f"no workspace with session_id={session_id}")
    else:
        raise SystemExit("need --session or --task")

    key = task_root.name
    acquire_followup_lock(task_root)
    try:
        meta = read_meta(task_root) or {}
        sid = str(meta.get("session_id") or session_id).strip()
        if not sid:
            raise SystemExit(f"meta missing session_id for {key}")
        result = resume_opencode(
            session_id=sid,
            prompt=prompt,
            cwd=task_root,
            print_live=True,
        )
        sync_result(
            task_root=task_root,
            result_dir=paths["result"],
            meta=meta,
        )
        if result.returncode != 0:
            print(f"opencode exit_code={result.returncode}", flush=True)
            return result.returncode
        print("ARCHIVE_FOLLOWUP_RESUME_OK", flush=True)
        return 0
    finally:
        release_followup_lock(task_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Module B: list per-task workspaces, or resume OpenCode in-place "
            "(requires .module_a_done)."
        )
    )
    parser.add_argument("--session", metavar="SESSION_ID", default="")
    parser.add_argument("--task", metavar="TASK_KEY", default="")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="",
        help="Follow-up prompt (required with --session/--task)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.session or args.task:
        prompt = (args.prompt or "").strip()
        if not prompt:
            parser.error("--session/--task requires a prompt argument")
        return run_followup(
            session_id=(args.session or "").strip(),
            task_key=(args.task or "").strip(),
            prompt=prompt,
        )
    print_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
