from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_service_logging(log_file: Path, *, level: int = logging.INFO) -> None:
    """Attach stdout + rotating file handlers once on the root logger."""
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_FMT)
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    target = str(log_file.resolve())

    has_stream = False
    has_file = False
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            if getattr(handler, "baseFilename", "") == target:
                has_file = True
        elif isinstance(handler, logging.StreamHandler):
            has_stream = True

    if not has_stream:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
    if not has_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
