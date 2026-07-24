import logging
from typing import Callable
from pathlib import Path

_log = logging.getLogger(__name__)

ROUTES: dict[str, Callable] = {}


def register(route_name: str, handler: Callable):
    ROUTES[route_name] = handler


def dispatch(payload: dict, source_path: Path):
    for key, body in payload.items():
        handler = ROUTES.get(key)
        if handler is None:
            _log.warning("unknown route skipped: %s (%s)", key, source_path.name)
            continue
        handler(body, source_path)
