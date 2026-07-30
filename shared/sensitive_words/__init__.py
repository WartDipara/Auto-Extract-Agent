"""
Shared sensitive-word table for post-extract CSV filtering / detection.

Word list: shared/sensitive_words/sensitive.txt (one word per line).
Matching: exact full-line match only (整行全字匹配).
Resume hit threshold is configured by callers (SENSITIVE_HIT_MIN).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SENSITIVE_FILE = _PACKAGE_DIR / "sensitive.txt"

_HEADER_NAMES = frozenset({"name", "word", "text", "敏感词"})
_MIN_WORD_LEN = 2

_cached_path: Path | None = None
_cached_words: frozenset[str] | None = None


def sensitive_words_path() -> Path:
    return DEFAULT_SENSITIVE_FILE


def load_sensitive_words(path: Path | None = None) -> frozenset[str]:
    global _cached_path, _cached_words
    target = Path(path) if path is not None else DEFAULT_SENSITIVE_FILE
    if _cached_words is not None and _cached_path == target:
        return _cached_words
    words: set[str] = set()
    if target.is_file():
        text = target.read_text(encoding="utf-8-sig", errors="replace")
        for raw in text.splitlines():
            w = raw.strip().strip(",").strip()
            if not w or w in _HEADER_NAMES or len(w) < _MIN_WORD_LEN:
                continue
            words.add(w)
    _cached_path = target
    _cached_words = frozenset(words)
    return _cached_words


def clear_sensitive_words_cache() -> None:
    global _cached_path, _cached_words
    _cached_path = None
    _cached_words = None


def _line_is_sensitive(line: str, table: frozenset[str] | set[str]) -> bool:
    return line in table


@dataclass(frozen=True)
class SensitiveHitResult:
    hit_lines: int
    samples: tuple[str, ...]


def scan_sensitive_hits(
    text: str,
    *,
    words: frozenset[str] | set[str] | None = None,
    sample_limit: int = 8,
) -> SensitiveHitResult:
    """Count content lines whose full text equals a sensitive word."""
    table = words if words is not None else load_sensitive_words()
    hits = 0
    samples: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "text":
            continue
        if _line_is_sensitive(line, table):
            hits += 1
            if len(samples) < sample_limit:
                samples.append(line[:80])
    return SensitiveHitResult(hit_lines=hits, samples=tuple(samples))


def filter_sensitive_lines(
    text: str,
    *,
    words: frozenset[str] | set[str] | None = None,
) -> tuple[str, int]:
    """Drop lines that exactly equal a sensitive word. Returns (body, removed)."""
    table = words if words is not None else load_sensitive_words()
    kept: list[str] = []
    removed = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line != "text" and _line_is_sensitive(line, table):
            removed += 1
            continue
        kept.append(line)
    body = "\n".join(kept)
    if body:
        body = body + "\n"
    return body, removed


def filter_sensitive_file(
    path: Path,
    *,
    words: frozenset[str] | set[str] | None = None,
) -> int:
    path = Path(path)
    if not path.is_file():
        return 0
    original = path.read_text(encoding="utf-8-sig", errors="replace")
    filtered, removed = filter_sensitive_lines(original, words=words)
    if removed:
        path.write_text(filtered, encoding="utf-8")
    return removed
