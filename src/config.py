"""
Central configuration for Hermes-Auto-Extract.

The external caller is a black box: it runs a fixed hermes command
and waits for a CSV file. All Hermes-internal settings (model,
provider, skills, MCP servers) are read by Hermes from hermes-home/
which is synced from config/ by setup.ps1 / sync.ps1.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Hermes workspace paths ──
HERMES_ROOT = PROJECT_ROOT / "hermes-home"
HERMES_APKS_DIR = HERMES_ROOT / "apks"
HERMES_OUTPUTS_DIR = HERMES_ROOT / "outputs"

# ── Pipeline paths ──
INBOX_DIR = PROJECT_ROOT / "inbox"
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
RESULT_DIR = PROJECT_ROOT / "result"
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_DIR = PROJECT_ROOT / "state"
PROCESSED_DIR = STATE_DIR / "processed"
QUEUE_FILE = STATE_DIR / "queue.json"
SESSIONS_FILE = STATE_DIR / "sessions.jsonl"

# ── Source config (synced to hermes-home/ by setup.ps1 / sync.ps1) ──
CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"

# ── Fixed black-box contract ──
# The external caller sends exactly this command to Hermes.
# Hermes reads model/provider/skills from hermes-home/config.yaml
# and hermes-home/skills/ on its own — no CLI injection needed.
HERMES_PROMPT = "开始获取文本任务"
HERMES_CMD = ["hermes", "chat", "-q", HERMES_PROMPT, "-v"]

# ── Task timing ──
HERMES_TIMEOUT_SEC = 3600
POLL_INTERVAL_SEC = 2.0
CSV_GRACE_SEC = 10.0
DECRYPT_FAIL_TEXT = "解密失败"
ABNORMAL_EXIT_TEXT = "异常退出"

# ── Download ──
DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_TIMEOUT_SEC = 300
AAPT_PATH = ""


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
