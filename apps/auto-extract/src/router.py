import logging
from typing import Callable
from pathlib import Path

_log = logging.getLogger(__name__)

ROUTES: dict[str, Callable] = {}


def register(route_name: str, handler: Callable):
    ROUTES[route_name] = handler


def dispatch(payload: dict, source_path: Path) -> bool:
    """Run matching handlers. Return True only if at least one accepts the file."""
    any_ok = False
    saw_route = False
    for key, body in payload.items():
        handler = ROUTES.get(key)
        if handler is None:
            _log.warning("unknown route skipped: %s (%s)", key, source_path.name)
            continue
        saw_route = True
        result = handler(body, source_path)
        if result is False:
            _log.warning("route rejected payload: %s (%s)", key, source_path.name)
            continue
        any_ok = True
    if not saw_route:
        _log.warning("no known route in inbox file: %s", source_path.name)
    return any_ok
