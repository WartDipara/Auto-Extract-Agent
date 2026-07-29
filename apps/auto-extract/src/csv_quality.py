"""Post-OpenCode CSV quality checks before archiving to result/.

Callers must run sensitive-word filtering first; line-count uses the
filtered tests.csv (see extract_bridge._apply_sensitive_filter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import config

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_MOJIBAKE_RE = re.compile(
    r"[ÃÂåæçèéêëìíîïðñòóôõöøùúûüýþÿÄÅÆÇÉÑÖØÜßÐÞ]"
)

# Single source for terminal failure markers (extend here only).
TERMINAL_MARKERS: tuple[tuple[str, str], ...] = (
    (config.ASSETS_MISSING_TEXT, "assets_missing"),
    (config.DECRYPT_FAIL_TEXT, "decrypt_failed"),
    (config.ABNORMAL_EXIT_TEXT, "abnormal_exit"),
)


@dataclass(frozen=True)
class QualityIssue:
    kind: str  # "empty" | "too_few" | "garbled"
    line_count: int
    garbled_lines: int
    detail: str


def _content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "text" and not lines:
            continue
        lines.append(line)
    return lines


def _line_matches_marker(cell: str, marker: str) -> bool:
    return cell == marker or cell.startswith(marker)


def match_terminal_status(text: str) -> str | None:
    """
    Return status if CSV is a terminal failure marker only (near-empty).
    Non-marker body lines > 0 => treat marker as hallucination and return None.
    """
    lines = _content_lines(text)
    if not lines:
        return None
    marker_status: str | None = None
    non_marker = 0
    for cell in lines:
        matched = False
        for marker, status in TERMINAL_MARKERS:
            if _line_matches_marker(cell, marker):
                marker_status = status
                matched = True
                break
        if not matched:
            non_marker += 1
    if non_marker > 0:
        return None
    return marker_status


def _is_terminal_marker(text: str) -> bool:
    return match_terminal_status(text) is not None


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
    Return first blocking issue, or None if OK / accepted terminal marker.
    Order: terminal skip → garbled → empty → too_few.
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

    if line_count == 0:
        return QualityIssue(
            kind="empty",
            line_count=0,
            garbled_lines=0,
            detail="line_count=0 (header-only or blank)",
        )

    if line_count < config.CSV_MIN_LINES:
        return QualityIssue(
            kind="too_few",
            line_count=line_count,
            garbled_lines=garbled,
            detail=f"line_count={line_count} < min={config.CSV_MIN_LINES}",
        )
    return None
