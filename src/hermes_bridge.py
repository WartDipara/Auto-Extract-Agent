import datetime
import logging
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_SEP = "=" * 60


def _clear_apks():
    config.HERMES_APKS_DIR.mkdir(parents=True, exist_ok=True)
    for path in config.HERMES_APKS_DIR.glob("*"):
        if path.is_file():
            path.unlink()
            _log.info("removed apk: %s", path.name)


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


def _csv_footer_status(csv_path: Path) -> str:
    if not csv_path.is_file():
        return "否"
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        return "是, 未知"
    status = classify_csv(text)
    if status == "decrypt_failed":
        return "是, 解密失败"
    return "是, 成功"


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}m {total % 60}s"


def _open_task_log(apk_name: str):
    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = _log_path_for_apk(apk_name)
        return path, path.open("w", encoding="utf-8")
    except OSError as exc:
        _log.error("cannot open task log for %s: %s", apk_name, exc)
        return None, None


def _stream_stdout(proc: subprocess.Popen, line_queue: queue.Queue):
    try:
        for line in proc.stdout:
            line_queue.put(line)
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


def place_apk(apk_path: Path) -> Path:
    _clear_apks()
    dest = config.HERMES_APKS_DIR / apk_path.name
    shutil.move(str(apk_path), str(dest))
    _log.info("placed apk: %s", dest)
    return dest


def invoke_hermes(apk_name: str) -> subprocess.CompletedProcess:
    stem = Path(apk_name).stem
    csv_path = _csv_path_for_apk(apk_name)
    start = datetime.datetime.now()
    timed_out = False
    stdout_chunks: list[str] = []
    log_path, log_fp = _open_task_log(apk_name)

    _log.info("invoking hermes: %s", " ".join(config.HERMES_CMD))
    proc = subprocess.Popen(
        config.HERMES_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
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
    if stripped == config.DECRYPT_FAIL_TEXT or stripped.startswith(
        config.DECRYPT_FAIL_TEXT
    ):
        return "decrypt_failed"
    for line in stripped.splitlines():
        cell = line.strip()
        if cell == config.DECRYPT_FAIL_TEXT or cell.startswith(config.DECRYPT_FAIL_TEXT):
            return "decrypt_failed"
    return "success"


def archive_csv(csv_path: Path, task_id: str, body_text: str) -> Path:
    config.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.RESULT_DIR / f"{task_id}_{csv_path.name}"
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
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(f" Session: {session_id}\n")
    except OSError as exc:
        _log.error("cannot append session to log %s: %s", log_path, exc)


def cleanup_apk(apk_name: str):
    target = config.HERMES_APKS_DIR / apk_name
    if target.is_file():
        target.unlink()
        _log.info("cleaned apk: %s", apk_name)
    for path in config.HERMES_APKS_DIR.glob("*.apk"):
        path.unlink()
        _log.info("cleaned leftover apk: %s", path.name)
