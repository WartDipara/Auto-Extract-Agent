"""Post-OpenCode CSV quality checks before archiving to result/.

Callers must run sensitive-word filtering first; line-count uses the
filtered tests.csv (see extract_bridge._apply_sensitive_filter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import config

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Common glyphs when UTF-8 Chinese is mis-decoded as Latin-1 / cp1252.
_MOJIBAKE_RE = re.compile(
    r"[ÃÂåæçèéêëìíîïðñòóôõöøùúûüýþÿÄÅÆÇÉÑÖØÜßÐÞ]"
)


@dataclass(frozen=True)
class QualityIssue:
    kind: str  # "too_few" | "garbled"
    line_count: int
    garbled_lines: int
    detail: str


def _content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
    return lines


def _is_terminal_marker(text: str) -> bool:
    stripped = text.strip()
    markers = (config.DECRYPT_FAIL_TEXT, config.ABNORMAL_EXIT_TEXT)
    if any(stripped == m or stripped.startswith(m) for m in markers):
        return True
    for line in stripped.splitlines():
        cell = line.strip()
        if any(cell == m or cell.startswith(m) for m in markers):
            return True
    return False


def line_looks_garbled(line: str) -> bool:
    if "\ufffd" in line:
        return True
    cjk = len(_CJK_RE.findall(line))
    moji = len(_MOJIBAKE_RE.findall(line))
    if moji >= 2 and cjk == 0 and len(line) >= 4:
        return True
    if moji >= 3 and moji > cjk:
        return True
    return False


def check_csv_quality(text: str) -> QualityIssue | None:
    """
    Return first blocking issue, or None if OK / skip markers.
    Garbled is checked before too_few (decrypt wrong makes count meaningless).
    """
    if _is_terminal_marker(text):
        return None
    lines = _content_lines(text)
    line_count = len(lines)
    garbled = sum(1 for line in lines if line_looks_garbled(line))
    ratio = (garbled / line_count) if line_count else 0.0

    if line_count > 0 and (
        garbled >= config.CSV_GARBLE_MIN_LINES or ratio >= config.CSV_GARBLE_RATIO
    ):
        return QualityIssue(
            kind="garbled",
            line_count=line_count,
            garbled_lines=garbled,
            detail=(
                f"garbled_lines={garbled}/{line_count} "
                f"(min={config.CSV_GARBLE_MIN_LINES}, ratio>={config.CSV_GARBLE_RATIO})"
            ),
        )

    if line_count < config.CSV_MIN_LINES:
        return QualityIssue(
            kind="too_few",
            line_count=line_count,
            garbled_lines=garbled,
            detail=f"line_count={line_count} < min={config.CSV_MIN_LINES}",
        )
    return None
