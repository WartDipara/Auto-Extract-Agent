"""
Shared sensitive-word table for post-extract CSV filtering.

Word list file: shared/sensitive_words/sensitive.txt (one word per line).
Both auto-extract and archive-followup may import this package.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SENSITIVE_FILE = _PACKAGE_DIR / "sensitive.txt"

# Skip common table header if present.
_HEADER_NAMES = frozenset({"name", "word", "text", "敏感词"})

_cached_path: Path | None = None
_cached_words: frozenset[str] | None = None


def sensitive_words_path() -> Path:
    return DEFAULT_SENSITIVE_FILE


def load_sensitive_words(path: Path | None = None) -> frozenset[str]:
    """Load word set from disk (cached per path)."""
    global _cached_path, _cached_words
    target = Path(path) if path is not None else DEFAULT_SENSITIVE_FILE
    if _cached_words is not None and _cached_path == target:
        return _cached_words
    words: set[str] = set()
    if target.is_file():
        text = target.read_text(encoding="utf-8-sig", errors="replace")
        for raw in text.splitlines():
            w = raw.strip()
            if not w or w in _HEADER_NAMES:
                continue
            words.add(w)
    _cached_path = target
    _cached_words = frozenset(words)
    return _cached_words


def clear_sensitive_words_cache() -> None:
    global _cached_path, _cached_words
    _cached_path = None
    _cached_words = None


def filter_sensitive_lines(
    text: str,
    *,
    words: frozenset[str] | set[str] | None = None,
) -> tuple[str, int]:
    """
    Drop lines whose stripped text exactly equals a sensitive word.
    Returns (filtered_text, removed_count). Preserves a trailing newline when
    any content remains.
    """
    table = words if words is not None else load_sensitive_words()
    kept: list[str] = []
    removed = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in table:
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
    """
    Rewrite CSV/text file in place with sensitive lines removed.
    Returns removed line count (0 if file missing).
    """
    path = Path(path)
    if not path.is_file():
        return 0
    original = path.read_text(encoding="utf-8-sig", errors="replace")
    filtered, removed = filter_sensitive_lines(original, words=words)
    if removed:
        path.write_text(filtered, encoding="utf-8")
    return removed
