import datetime
import logging
import re
import subprocess
import time
from pathlib import Path

import config
from shared.archive_contract import sanitize_label_for_filename

_log = logging.getLogger(__name__)

_SEP = "=" * 60

# Serial A only: current task workspace root for this module.
_task_root: Path | None = None


def _require_task_root() -> Path:
    if _task_root is None:
        raise RuntimeError("task_root not set")
    return _task_root


def opencode_output_csv() -> Path:
    from shared.archive_contract import task_layout

    return task_layout(_require_task_root())["tests_csv"].resolve()


def result_csv_path(apk_name: str) -> Path:
    _ = apk_name
    return opencode_output_csv()


def _log_path_for_apk(apk_name: str) -> Path:
    stem = Path(apk_name).stem
    return config.LOGS_DIR / f"{stem}.log"


def _safe_write(fp, text: str):
    if fp is None:
        return
    try:
        fp.write(text)
        fp.flush()
    except OSError:
        pass


def _csv_footer_status(csv_path: Path) -> str:
    if not csv_path.is_file():
        return "否"
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        return "是, 未知"
    status = classify_csv(text)
    if status == "decrypt_failed":
        return "是, 解密失败"
    if status == "assets_missing":
        return "是, 资源缺失"
    if status == "abnormal_exit":
        return "是, 异常退出"
    return "是, 成功"


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}m {total % 60}s"


def _open_task_log(apk_name: str):
    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = _log_path_for_apk(apk_name)
        return path, path.open("w", encoding="utf-8-sig", newline="\n")
    except OSError as exc:
        _log.error("cannot open task log for %s: %s", apk_name, exc)
        return None, None


def write_decrypt_fail_csv(apk_name: str, reason: str = "") -> Path:
    from shared.archive_contract import task_layout

    layout = task_layout(_require_task_root())
    layout["outputs"].mkdir(parents=True, exist_ok=True)
    csv_path = layout["tests_csv"]
    detail = reason or f"超时，超过 {config.AGENT_TIMEOUT_SEC} 秒，进程已被终止"
    csv_path.write_text(
        f"text\n{config.DECRYPT_FAIL_TEXT}（{detail}）\n",
        encoding="utf-8-sig",
    )
    _log.info("wrote decrypt-fail csv: %s", csv_path)
    return csv_path


def write_abnormal_exit_csv(apk_name: str, reason: str = "") -> Path:
    from shared.archive_contract import task_layout

    layout = task_layout(_require_task_root())
    layout["outputs"].mkdir(parents=True, exist_ok=True)
    csv_path = layout["tests_csv"]
    detail = reason or "opencode 进程已结束但未产出 CSV"
    csv_path.write_text(
        f"text\n{config.ABNORMAL_EXIT_TEXT}（{detail}）\n",
        encoding="utf-8-sig",
    )
    _log.info("wrote abnormal-exit csv: %s", csv_path)
    return csv_path


def csv_has_content(apk_name: str) -> bool:
    csv_path = result_csv_path(apk_name)
    if not csv_path.is_file():
        return False
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    return bool(text)


def ensure_csv_after_agent(apk_name: str, returncode: int) -> Path:
    if csv_has_content(apk_name):
        return result_csv_path(apk_name)
    agent = "opencode"
    if returncode != 0:
        reason = f"{agent} 非零退出 exit={returncode}，未产出 CSV"
    else:
        reason = f"{agent} 对话提前结束（进程已退出），未产出 CSV"
    return write_abnormal_exit_csv(apk_name, reason=reason)


def read_session_id_from_log(apk_name: str) -> str:
    log_path = _log_path_for_apk(apk_name)
    if not log_path.is_file():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    for pattern in (
        r"Session:\s+(\S+)",
        r"CLI cleanup calling memory shutdown for session\s+(\S+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    n = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                n += 1
    except OSError:
        pass
    return n


def workspace_ready_snapshot(task_root: Path | None = None) -> dict:
    from shared.archive_contract import task_layout

    root = Path(task_root) if task_root is not None else _require_task_root()
    layout = task_layout(root)
    return {
        "root": str(layout["root"].resolve()),
        "decoded_dir": str(layout["decoded"].resolve()),
        "hotfix_dir": str(layout["hotfix"].resolve()),
        "outputs_dir": str(layout["outputs"].resolve()),
        "decoded_files": _count_files(layout["decoded"]),
        "hotfix_files": _count_files(layout["hotfix"]),
        "decoded_exists": layout["decoded"].is_dir(),
        "hotfix_exists": layout["hotfix"].is_dir(),
    }


def assert_workspace_ready(task_root: Path | None = None) -> dict:
    snap = workspace_ready_snapshot(task_root)
    if snap["decoded_files"] <= 0 and snap["hotfix_files"] <= 0:
        raise RuntimeError(
            f"refuse agent: decoded/ and hotfix/ both empty under {snap['root']}"
        )
    _log.info(
        "workspace ready: decoded_files=%s hotfix_files=%s root=%s",
        snap["decoded_files"],
        snap["hotfix_files"],
        snap["root"],
    )
    print(
        f"workspace ready decoded_files={snap['decoded_files']} "
        f"hotfix_files={snap['hotfix_files']}",
        flush=True,
    )
    return snap


def _opencode_prompt_slots(apk_name: str, snap: dict) -> dict:
    tests_csv = str(opencode_output_csv())
    return {
        "skill": config.OPENCODE_SKILL,
        "root": snap["root"],
        "decoded_dir": snap["decoded_dir"],
        "hotfix_dir": snap["hotfix_dir"],
        "outputs_dir": snap["outputs_dir"],
        "apk_name": apk_name,
        "apk_stem": Path(apk_name).stem,
        "decoded_files": snap["decoded_files"],
        "hotfix_files": snap["hotfix_files"],
        "tests_csv": tests_csv,
    }


def build_opencode_prompt(apk_name: str, snap: dict | None = None) -> str:
    """Render opencode.initial from config/prompts.json."""
    import prompts as prompt_store

    snap = snap or workspace_ready_snapshot()
    return prompt_store.render(
        "opencode.initial", **_opencode_prompt_slots(apk_name, snap)
    )


def build_opencode_resume_prompt(
    kind: str, apk_name: str, snap: dict | None = None, **extra_slots
) -> str:
    """kind: stall_continue | deadline_persist | missing_output | final_csv_review | large_csv_review | quality_*."""
    import prompts as prompt_store

    snap = snap or workspace_ready_snapshot()
    slots = _opencode_prompt_slots(apk_name, snap)
    slots.update(extra_slots)
    return prompt_store.render(f"opencode.resume.{kind}", **slots)


def build_opencode_cmd(prompt: str) -> list[str]:
    """Preview helper for tests; production uses OpenCodeSessionManager."""
    import shutil

    exe = shutil.which(config.OPENCODE_CMD) or config.OPENCODE_CMD
    root = str(_task_root.resolve()) if _task_root is not None else str(config.WORKSPACE_ROOT.resolve())
    return [
        exe,
        "run",
        "--command",
        config.OPENCODE_SKILL,
        "--auto",
        "--variant",
        config.OPENCODE_VARIANT,
        "--dir",
        root,
        prompt,
    ]


def _opencode_tests_ok() -> bool:
    from opencode_session import output_csv_has_content

    return output_csv_has_content(opencode_output_csv())


def _append_opencode_task_log(
    log_fp,
    *,
    phase: str,
    prompt: str,
    result,
) -> None:
    _safe_write(
        log_fp,
        (
            f"\n--- phase={phase} ---\n"
            f"session={getattr(result, 'session_id', '') or '-'}\n"
            f"exit={getattr(result, 'returncode', '')}\n"
            f"stalled={getattr(result, 'stalled', False)}\n"
            f"prompt={prompt}\n"
        ),
    )


def invoke_opencode(apk_name: str, *, task_root: Path) -> subprocess.CompletedProcess:
    """
    OpenCode 黑盒：一任务一 session；两段 stall 看门狗；缺产物 resume。
    返回前保证 tests.csv 存在（成功内容或解密失败标记）。
    """
    global _task_root
    from opencode_session import OpenCodeSessionManager
    from shared.archive_contract import task_layout

    _task_root = Path(task_root).resolve()
    workspace = _task_root
    snap = assert_workspace_ready(workspace)
    task_key = Path(apk_name).stem
    layout = task_layout(workspace)
    layout["outputs"].mkdir(parents=True, exist_ok=True)
    out_csv = layout["tests_csv"]
    if out_csv.is_file():
        try:
            out_csv.unlink()
        except OSError:
            pass

    mgr = OpenCodeSessionManager()
    log_path, log_fp = _open_task_log(apk_name)
    start = datetime.datetime.now()
    _safe_write(
        log_fp,
        (
            f"{_SEP}\n"
            f" Task: {task_key}\n"
            f" Agent: opencode\n"
            f" Start: {start.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f" Workspace: {workspace}\n"
            f" Output: {out_csv}\n"
            f" Inventory: decoded_files={snap['decoded_files']} "
            f"hotfix_files={snap['hotfix_files']}\n"
            f"{_SEP}\n"
        ),
    )

    stall_sec = float(config.OPENCODE_STALL_SEC)
    hard_timeout = float(config.AGENT_TIMEOUT_SEC)
    last_result = None
    stdout_parts: list[str] = []
    forced_decrypt_fail = False

    stop_path = layout["stop"]

    def _run(phase: str, prompt: str, *, force_new: bool, skill: str | None, use_stall: bool):
        nonlocal last_result
        print(f"opencode phase={phase}", flush=True)
        result = mgr.run(
            task_key=task_key,
            prompt=prompt,
            cwd=workspace,
            skill=skill,
            force_new=force_new,
            print_live=True,
            stall_sec=stall_sec if use_stall else None,
            stall_output_path=out_csv if use_stall else None,
            hard_timeout_sec=hard_timeout,
            stop_path=stop_path,
        )
        last_result = result
        if result.stdout_text:
            stdout_parts.append(result.stdout_text)
        _append_opencode_task_log(log_fp, phase=phase, prompt=prompt, result=result)
        reason = getattr(result, "kill_reason", None)
        if reason in ("stop", "interrupt"):
            from opencode_session import OpenCodeStopped

            raise OpenCodeStopped(f"opencode {reason}")
        return result

    # --- segment 1: initial ---
    initial = build_opencode_prompt(apk_name, snap)
    r1 = _run(
        "initial",
        initial,
        force_new=True,
        skill=config.OPENCODE_SKILL,
        use_stall=True,
    )

    if _opencode_tests_ok():
        # CSV already on disk (including stall-time write); skip missing_output.
        pass
    elif getattr(r1, "kill_reason", None) == "hard_timeout":
        write_decrypt_fail_csv(apk_name, reason="OpenCode 硬超时且未产出 tests.csv")
    elif r1.stalled:
        # This run hit OPENCODE_STALL_SEC with no content → one continue.
        cont = build_opencode_resume_prompt("stall_continue", apk_name, snap)
        r2 = _run(
            "stall_continue",
            cont,
            force_new=False,
            skill=None,
            use_stall=True,
        )
        if _opencode_tests_ok():
            pass
        elif getattr(r2, "kill_reason", None) == "hard_timeout":
            write_decrypt_fail_csv(apk_name, reason="OpenCode 硬超时且未产出 tests.csv")
        elif r2.stalled:
            # Second stall budget exhausted → force terminal decrypt_failed (marker only).
            dump = build_opencode_resume_prompt("deadline_persist", apk_name, snap)
            _run(
                "deadline_persist",
                dump,
                force_new=False,
                skill=None,
                use_stall=False,
            )
            forced_decrypt_fail = True
            write_decrypt_fail_csv(
                apk_name,
                reason="已满一小时，催促落盘后仍判定为解密失败",
            )
        else:
            _resume_missing_output(mgr, apk_name, snap, task_key, _run)
    else:
        _resume_missing_output(mgr, apk_name, snap, task_key, _run)

    if forced_decrypt_fail:
        print("skip quality gate: forced decrypt_failed", flush=True)
    elif not _opencode_tests_ok():
        write_decrypt_fail_csv(apk_name, reason="OpenCode 结束后仍无有效 tests.csv")
    else:
        _ask_final_csv_review(apk_name, snap, _run)
        _resume_quality_gate(mgr, apk_name, snap, task_key, _run)
        _ask_large_csv_review(apk_name, snap, _run)

    end = datetime.datetime.now()
    duration = (end - start).total_seconds()
    returncode = 0 if last_result is None else last_result.returncode
    session_id = "" if last_result is None else (last_result.session_id or "")
    if not session_id:
        session_id = mgr.lookup_session_id(task_key)
    export_path = layout["opencode_export"]
    export_ok = False
    if session_id:
        try:
            from opencode_session import export_session_json

            export_session_json(session_id, cwd=workspace, out_path=export_path)
            export_ok = True
        except Exception as exc:
            _log.warning("opencode export failed session=%s: %s", session_id, exc)
            print(f"opencode export failed: {exc}", flush=True)
    else:
        _log.warning("skip opencode export: no session_id for task=%s", task_key)

    csv_status = _csv_footer_status(out_csv)
    _safe_write(
        log_fp,
        (
            f"\n{_SEP}\n"
            f" Finish: {end.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f" Duration: {_format_duration(duration)}\n"
            f" Exit Code: {returncode}\n"
            f" Session: {session_id}\n"
            f" ForcedDecryptFail: {forced_decrypt_fail}\n"
            f" CSV: {out_csv} ({csv_status})\n"
            f" Export: {export_path if export_ok else '(skipped/failed)'}\n"
            f"{_SEP}\n"
        ),
    )
    if log_fp is not None:
        try:
            log_fp.close()
        except OSError:
            pass
    if log_path is not None:
        _log.info("task log written: %s", log_path)

    print(f"opencode done csv={out_csv} status={csv_status}", flush=True)
    return subprocess.CompletedProcess(
        args=["opencode", "run", task_key],
        returncode=returncode,
        stdout="".join(stdout_parts),
        stderr="",
    )


def _resume_missing_output(mgr, apk_name, snap, task_key, run_fn):
    """进程已退出但无 tests.csv：同 session resume.missing_output，最多 N 次。"""
    for i in range(1, config.OPENCODE_MISSING_OUTPUT_MAX + 1):
        if _opencode_tests_ok():
            return
        if not mgr.lookup_session_id(task_key):
            _log.error("no session_id for missing_output resume task=%s", task_key)
            return
        prompt = build_opencode_resume_prompt("missing_output", apk_name, snap)
        print(
            f"opencode missing_output resume {i}/{config.OPENCODE_MISSING_OUTPUT_MAX}",
            flush=True,
        )
        run_fn(
            f"missing_output_{i}",
            prompt,
            force_new=False,
            skill=None,
            use_stall=False,
        )
        if _opencode_tests_ok():
            return


def _read_tests_csv_text() -> str:
    path = opencode_output_csv()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _apply_sensitive_filter() -> int:
    """Drop tests.csv lines that contain sensitive substrings."""
    from shared.sensitive_words import filter_sensitive_file

    path = opencode_output_csv()
    removed = filter_sensitive_file(path)
    if removed:
        print(f"sensitive filter removed {removed} lines", flush=True)
        _log.info("sensitive filter removed %s lines from %s", removed, path.name)
    return removed


def _detect_quality_issue(text: str) -> tuple[str | None, dict]:
    """
    Return (prompt_kind, slots) or (None, {}).
    Order: terminal → empty → garbled → sensitive → too_few.
    """
    from csv_quality import check_csv_quality, match_terminal_status
    from shared.sensitive_words import scan_sensitive_hits

    if match_terminal_status(text) is not None:
        return None, {}

    issue = check_csv_quality(text)
    if issue is not None and issue.kind == "empty":
        return "empty", {}
    if issue is not None and issue.kind == "garbled":
        return "quality_garbled", {
            "line_count": issue.line_count,
            "min_lines": config.CSV_MIN_LINES,
            "garbled_lines": issue.garbled_lines,
        }

    hit = scan_sensitive_hits(text)
    if hit.hit_lines >= config.SENSITIVE_HIT_MIN:
        samples = "；".join(hit.samples) if hit.samples else "-"
        return "quality_sensitive", {
            "hit_lines": hit.hit_lines,
            "samples": samples,
        }

    if issue is not None and issue.kind == "too_few":
        return "quality_too_few", {
            "line_count": issue.line_count,
            "min_lines": config.CSV_MIN_LINES,
            "garbled_lines": issue.garbled_lines,
        }
    return None, {}


def _resume_quality_gate(mgr, apk_name, snap, task_key, run_fn):
    """
    Single loop: empty→classify up to EMPTY_CLASSIFY_MAX; others→resume up to N.
    After pass, filter sensitive lines and re-check once.
    """
    from csv_quality import match_terminal_status

    if not mgr.lookup_session_id(task_key):
        _log.error("no session_id for quality resume task=%s", task_key)
        return

    empty_left = max(0, int(config.OPENCODE_EMPTY_CLASSIFY_MAX))
    resumes_left = max(0, int(config.OPENCODE_QUALITY_RESUME_MAX))

    while True:
        text = _read_tests_csv_text()
        if match_terminal_status(text) is not None:
            return

        kind, slots = _detect_quality_issue(text)
        if kind is None:
            removed = _apply_sensitive_filter()
            if removed:
                again, _ = _detect_quality_issue(_read_tests_csv_text())
                if again is not None:
                    continue
            print("csv quality ok", flush=True)
            return

        if kind == "empty":
            if empty_left <= 0:
                write_decrypt_fail_csv(apk_name, reason="空结果未声明原因")
                print("csv empty forced decrypt_failed", flush=True)
                return
            empty_left -= 1
            _ask_empty_classify(apk_name, snap, run_fn)
            continue

        if resumes_left <= 0:
            _apply_sensitive_filter()
            print(
                f"csv quality unresolved after resumes: {kind} {slots}; proceed",
                flush=True,
            )
            _log.warning("csv quality unresolved kind=%s slots=%s", kind, slots)
            return

        resumes_left -= 1
        prompt = build_opencode_resume_prompt(kind, apk_name, snap, **slots)
        used = max(0, int(config.OPENCODE_QUALITY_RESUME_MAX)) - resumes_left
        print(
            f"opencode {kind} resume {used}/{config.OPENCODE_QUALITY_RESUME_MAX}: {slots}",
            flush=True,
        )
        _log.warning("csv quality fail %s %s", kind, slots)
        run_fn(
            f"{kind}_{used}",
            prompt,
            force_new=False,
            skill=None,
            use_stall=False,
        )


def _ask_final_csv_review(apk_name, snap, run_fn):
    """One post-extract pass: ask OpenCode to scrub garbled / truncated / comments / bad rows."""
    prompt = build_opencode_resume_prompt("final_csv_review", apk_name, snap)
    print("opencode final_csv_review", flush=True)
    run_fn(
        "final_csv_review",
        prompt,
        force_new=False,
        skill=None,
        use_stall=False,
    )


def _content_line_count(text: str) -> int:
    lines = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "text" and lines == 0:
            continue
        lines += 1
    return lines


def _ask_large_csv_review(apk_name, snap, run_fn):
    """If CSV is huge, one extra OpenCode pass focused on garbled / banned words."""
    from csv_quality import match_terminal_status

    text = _read_tests_csv_text()
    if match_terminal_status(text) is not None:
        return
    line_count = _content_line_count(text)
    threshold = max(0, int(config.CSV_LARGE_REVIEW_LINES))
    if line_count <= threshold:
        return
    prompt = build_opencode_resume_prompt(
        "large_csv_review",
        apk_name,
        snap,
        line_count=line_count,
        large_lines=threshold,
    )
    print(
        f"opencode large_csv_review: lines={line_count} > {threshold}",
        flush=True,
    )
    run_fn(
        "large_csv_review",
        prompt,
        force_new=False,
        skill=None,
        use_stall=False,
    )
    _apply_sensitive_filter()


def _ask_empty_classify(apk_name, snap, run_fn):
    """One OpenCode turn asking for assets_missing or decrypt_failed marker."""
    from csv_quality import check_csv_quality, match_terminal_status

    text = _read_tests_csv_text()
    if match_terminal_status(text) is not None:
        return
    issue = check_csv_quality(text)
    if issue is None or issue.kind != "empty":
        return
    prompt = build_opencode_resume_prompt("classify_empty", apk_name, snap)
    print(f"opencode classify_empty: {issue.detail}", flush=True)
    run_fn(
        "classify_empty",
        prompt,
        force_new=False,
        skill=None,
        use_stall=False,
    )


def invoke_extract_agent(apk_name: str, *, task_root: Path) -> subprocess.CompletedProcess:
    """Run OpenCode black-box extract."""
    _log.info("extract agent=opencode apk=%s root=%s", apk_name, task_root)
    print("extract agent=opencode", flush=True)
    return invoke_opencode(apk_name, task_root=task_root)


def wait_for_csv(apk_name: str, timeout_sec: float | None = None) -> tuple[Path, str]:
    deadline = time.monotonic() + (timeout_sec or config.AGENT_TIMEOUT_SEC)
    csv_path = result_csv_path(apk_name)
    while time.monotonic() < deadline:
        if csv_path.is_file():
            text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
            if text:
                return csv_path, text
        time.sleep(config.POLL_INTERVAL_SEC)
    raise TimeoutError(f"csv timeout: {csv_path.name}")


def classify_csv(text: str) -> str:
    from csv_quality import match_terminal_status

    status = match_terminal_status(text)
    return status if status is not None else "success"


def archive_csv(csv_path: Path, apk_stem: str, label: str, body_text: str) -> Path:
    """Write result CSV; split 简/繁 when both sides have lines.

    Pure simplified or pure traditional -> one file (original name + full body).
    Mixed -> ``{stem}_{label}.csv`` (simplified) + ``{stem}_{label}_T.csv`` (traditional).
    """
    config.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = sanitize_label_for_filename(label)
    dest = config.RESULT_DIR / f"{apk_stem}_{safe_label}.csv"

    try:
        from zh_script import join_csv_body, split_body_text

        split = split_body_text(body_text)
    except ImportError:
        _log.warning("hanzidentifier missing; archive without script split")
        dest.write_text(body_text, encoding="utf-8-sig")
        _log.info("result csv: %s", dest)
        return dest

    if split.is_pure:
        dest.write_text(body_text, encoding="utf-8-sig")
        _log.info(
            "result csv (pure script): %s simp=%s trad=%s",
            dest,
            len(split.simplified_lines),
            len(split.traditional_lines),
        )
        print(
            f"result csv: {dest} "
            f"(pure simp={len(split.simplified_lines)} trad={len(split.traditional_lines)})",
            flush=True,
        )
        return dest

    dest.write_text(join_csv_body(split.simplified_lines), encoding="utf-8-sig")
    dest_t = config.RESULT_DIR / f"{apk_stem}_{safe_label}_T.csv"
    dest_t.write_text(join_csv_body(split.traditional_lines), encoding="utf-8-sig")
    _log.info(
        "result csv split: %s (%s) + %s (%s)",
        dest,
        len(split.simplified_lines),
        dest_t,
        len(split.traditional_lines),
    )
    print(
        f"result csv: {dest} ({len(split.simplified_lines)} simplified)",
        flush=True,
    )
    print(
        f"result csv: {dest_t} ({len(split.traditional_lines)} traditional)",
        flush=True,
    )
    return dest


def append_session_to_log(apk_name: str, session_id: str):
    if not session_id:
        return
    log_path = _log_path_for_apk(apk_name)
    if not log_path.is_file():
        return
    try:
        with log_path.open("a", encoding="utf-8", newline="\n") as fp:
            fp.write(f" Session: {session_id}\n")
    except OSError as exc:
        _log.error("cannot append session to log %s: %s", log_path, exc)


def cleanup_download_apk(apk_name: str = ""):
    """Delete downloads/ APK only; task workspace is kept for followup."""
    name = Path(apk_name).name if apk_name else ""
    if not name:
        return
    apk_path = config.DOWNLOADS_DIR / name
    if apk_path.is_file():
        try:
            apk_path.unlink()
            _log.info("removed download apk: %s", apk_path.name)
            print(f"removed download {apk_path.name}", flush=True)
        except OSError as exc:
            _log.error("cannot remove download apk %s: %s", apk_path, exc)
