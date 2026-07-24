import datetime
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import config
from apk_meta import sanitize_label_for_filename

_log = logging.getLogger(__name__)

_SEP = "=" * 60
_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)


def _clear_apks():
    config.HERMES_APKS_DIR.mkdir(parents=True, exist_ok=True)
    for path in list(config.HERMES_APKS_DIR.iterdir()):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
                _log.info("removed apk entry: %s", path.name)
            elif path.is_dir():
                shutil.rmtree(path)
                _log.info("removed apk dir: %s", path.name)
        except OSError as exc:
            _log.error("cannot remove %s: %s", path, exc)


def ensure_workspace_clean() -> bool:
    """任务开始/结束时检查并清空 apks 工作区。返回是否曾有残留。"""
    config.HERMES_APKS_DIR.mkdir(parents=True, exist_ok=True)
    leftovers = list(config.HERMES_APKS_DIR.iterdir())
    if not leftovers:
        return False
    names = ", ".join(p.name for p in leftovers)
    _log.warning("apks workspace not empty before clean: %s", names)
    _clear_apks()
    return True


def _csv_path_for_apk(apk_name: str) -> Path:
    stem = Path(apk_name).stem
    return config.HERMES_OUTPUTS_DIR / f"{stem}.csv"


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


def _decode_stdout_bytes(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _escape_for_log(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for ch in text:
        code = ord(ch)
        if ch == "\n" or ch == "\t":
            out.append(ch)
        elif code < 32 or code == 127:
            out.append(f"\\x{code:02x}")
        elif 0x80 <= code <= 0x9F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _csv_footer_status(csv_path: Path) -> str:
    if not csv_path.is_file():
        return "否"
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        return "是, 未知"
    status = classify_csv(text)
    if status == "decrypt_failed":
        return "是, 解密失败"
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


def _stream_stdout(proc: subprocess.Popen, line_queue: queue.Queue):
    try:
        while True:
            raw = proc.stdout.readline()
            if raw == b"":
                break
            line_queue.put(_escape_for_log(_decode_stdout_bytes(raw)))
    finally:
        line_queue.put(None)


def write_decrypt_fail_csv(apk_name: str, reason: str = "") -> Path:
    config.HERMES_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _csv_path_for_apk(apk_name)
    detail = reason or f"超时，超过 {config.HERMES_TIMEOUT_SEC} 秒，进程已被终止"
    csv_path.write_text(
        f"text\n{config.DECRYPT_FAIL_TEXT}（{detail}）\n",
        encoding="utf-8-sig",
    )
    _log.info("wrote decrypt-fail csv: %s", csv_path)
    return csv_path


def write_abnormal_exit_csv(apk_name: str, reason: str = "") -> Path:
    config.HERMES_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _csv_path_for_apk(apk_name)
    detail = reason or "Hermes 进程已结束但未产出 CSV"
    csv_path.write_text(
        f"text\n{config.ABNORMAL_EXIT_TEXT}（{detail}）\n",
        encoding="utf-8-sig",
    )
    _log.info("wrote abnormal-exit csv: %s", csv_path)
    return csv_path


def csv_has_content(apk_name: str) -> bool:
    csv_path = _csv_path_for_apk(apk_name)
    if not csv_path.is_file():
        return False
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    return bool(text)


def ensure_csv_after_hermes(apk_name: str, returncode: int) -> Path:
    """Hermes 退出后若无 CSV，立即写入异常退出标记；不做长时间空等。"""
    if csv_has_content(apk_name):
        return _csv_path_for_apk(apk_name)
    deadline = time.monotonic() + config.CSV_GRACE_SEC
    while time.monotonic() < deadline:
        if csv_has_content(apk_name):
            return _csv_path_for_apk(apk_name)
        time.sleep(0.5)
    if returncode != 0:
        reason = f"Hermes 非零退出 exit={returncode}，未产出 CSV"
    else:
        reason = "Hermes 对话提前结束（进程已退出），未产出 CSV"
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
        r"hermes --resume\s+(\S+)",
        r"Session:\s+(\S+)",
        r"CLI cleanup calling memory shutdown for session\s+(\S+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def place_apk(apk_path: Path) -> Path:
    ensure_workspace_clean()
    dest = config.HERMES_APKS_DIR / apk_path.name
    shutil.move(str(apk_path), str(dest))
    _log.info("placed apk: %s", dest)
    return dest


def _hermes_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def invoke_hermes(apk_name: str) -> subprocess.CompletedProcess:
    stem = Path(apk_name).stem
    csv_path = _csv_path_for_apk(apk_name)
    start = datetime.datetime.now()
    timed_out = False
    stdout_chunks: list[str] = []
    log_path, log_fp = _open_task_log(apk_name)
    workspace = str(config.HERMES_ROOT.resolve())
    agent_home = os.environ.get("HERMES_HOME", "(unset)")

    _log.info(
        "invoking hermes: %s (HERMES_HOME=%s cwd=%s)",
        " ".join(config.HERMES_CMD),
        agent_home,
        workspace,
    )
    proc = subprocess.Popen(
        config.HERMES_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        cwd=workspace,
        env=_hermes_env(),
    )

    _safe_write(
        log_fp,
        (
            f"{_SEP}\n"
            f" Task: {stem}\n"
            f" Start: {start.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f" PID: {proc.pid}\n"
            f"{_SEP}\n\n"
        ),
    )

    line_queue: queue.Queue = queue.Queue()
    reader = threading.Thread(
        target=_stream_stdout,
        args=(proc, line_queue),
        name=f"hermes-stdout-{stem}",
        daemon=True,
    )
    reader.start()

    deadline = time.monotonic() + config.HERMES_TIMEOUT_SEC
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            line = line_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            if proc.poll() is not None:
                while True:
                    try:
                        line = line_queue.get_nowait()
                    except queue.Empty:
                        line = None
                        break
                    if line is None:
                        break
                    stdout_chunks.append(line)
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    _safe_write(log_fp, f"[{ts}] {line}")
                break
            continue
        if line is None:
            break
        stdout_chunks.append(line)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        _safe_write(log_fp, f"[{ts}] {line}")

    if timed_out:
        _log.error(
            "hermes timed out after %ss, external write decrypt-fail csv",
            config.HERMES_TIMEOUT_SEC,
        )
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        _safe_write(
            log_fp,
            f"\n[!!!] TIMEOUT after {config.HERMES_TIMEOUT_SEC}s\n",
        )
        write_decrypt_fail_csv(apk_name)
        returncode = 0
        stdout_text = "解密失败（超时）"
    else:
        returncode = proc.wait()
        stdout_text = "".join(stdout_chunks)

    end = datetime.datetime.now()
    duration = (end - start).total_seconds()
    csv_status = _csv_footer_status(csv_path)
    _safe_write(
        log_fp,
        (
            f"\n{_SEP}\n"
            f" Finish: {end.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f" Duration: {_format_duration(duration)}\n"
            f" Exit Code: {returncode}\n"
            f" CSV: {csv_path} ({csv_status})\n"
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

    return subprocess.CompletedProcess(
        args=config.HERMES_CMD,
        returncode=returncode,
        stdout=stdout_text,
        stderr="",
    )


def wait_for_csv(apk_name: str, timeout_sec: float | None = None) -> tuple[Path, str]:
    deadline = time.monotonic() + (timeout_sec or config.HERMES_TIMEOUT_SEC)
    csv_path = _csv_path_for_apk(apk_name)
    while time.monotonic() < deadline:
        if csv_path.is_file():
            text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
            if text:
                return csv_path, text
        time.sleep(config.POLL_INTERVAL_SEC)
    raise TimeoutError(f"csv timeout: {csv_path.name}")


def clean_result_csv(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    session_id = ""
    if lines and lines[0].strip() == "text":
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("__SESSION_ID__:"):
        session_id = lines[-1].split(":", 1)[1].strip()
        lines = lines[:-1]
    body = "\n".join(lines).strip("\n")
    if body:
        body = body + "\n"
    return body, session_id


def classify_csv(text: str) -> str:
    stripped = text.strip()
    markers = (
        (config.ABNORMAL_EXIT_TEXT, "abnormal_exit"),
        (config.DECRYPT_FAIL_TEXT, "decrypt_failed"),
    )
    for marker, status in markers:
        if stripped == marker or stripped.startswith(marker):
            return status
    for line in stripped.splitlines():
        cell = line.strip()
        for marker, status in markers:
            if cell == marker or cell.startswith(marker):
                return status
    return "success"


def archive_csv(csv_path: Path, apk_stem: str, label: str, body_text: str) -> Path:
    config.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = sanitize_label_for_filename(label)
    dest = config.RESULT_DIR / f"{apk_stem}_{safe_label}.csv"
    dest.write_text(body_text, encoding="utf-8-sig")
    if csv_path.is_file():
        csv_path.unlink()
    _log.info("archived csv: %s", dest)
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


def cleanup_apk(apk_name: str = ""):
    """清空 Hermes apks 工作区（含 apk 文件与解包残留目录）。"""
    _ = apk_name
    ensure_workspace_clean()
    _log.info("cleaned hermes apks workspace")
