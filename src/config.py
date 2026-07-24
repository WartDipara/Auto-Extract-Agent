from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

HERMES_ROOT = PROJECT_ROOT / "hermes-home"
HERMES_APKS_DIR = HERMES_ROOT / "apks"
HERMES_OUTPUTS_DIR = HERMES_ROOT / "outputs"

INBOX_DIR = PROJECT_ROOT / "inbox"
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
RESULT_DIR = PROJECT_ROOT / "result"
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_DIR = PROJECT_ROOT / "state"
PROCESSED_DIR = STATE_DIR / "processed"
QUEUE_FILE = STATE_DIR / "queue.json"
SESSIONS_FILE = STATE_DIR / "sessions.jsonl"

HERMES_PROMPT = "开始获取文本任务"
HERMES_CMD = ["hermes", "chat", "-q", HERMES_PROMPT, "-v"]
HERMES_TIMEOUT_SEC = 3600
POLL_INTERVAL_SEC = 2.0
DECRYPT_FAIL_TEXT = "解密失败"

DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_TIMEOUT_SEC = 300


def ensure_dirs():
    for path in (
        INBOX_DIR,
        DOWNLOADS_DIR,
        RESULT_DIR,
        LOGS_DIR,
        STATE_DIR,
        PROCESSED_DIR,
        HERMES_APKS_DIR,
        HERMES_OUTPUTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
