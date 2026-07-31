"""Classify extract CSV lines as simplified vs traditional Chinese."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptSplit:
    simplified_lines: list[str]
    traditional_lines: list[str]

    @property
    def is_pure(self) -> bool:
        """True when one side is empty (100% the other, or no data)."""
        return not self.simplified_lines or not self.traditional_lines


def route_bucket(text: str) -> str:
    """Return 's' or 't' for one line. Every line must go to exactly one side."""
    import hanzidentifier as hz
    from hanzidentifier import helpers

    kind = hz.identify(text)
    if kind is hz.TRADITIONAL:
        return "t"
    if kind is hz.SIMPLIFIED:
        return "s"
    if kind is hz.BOTH:
        return "s"
    if kind is hz.UNKNOWN:
        return "s"
    if kind is hz.MIXED:
        chinese = helpers.get_hanzi(text)
        exclusive_trad = chinese - helpers.SIMPLIFIED_CHARACTERS
        exclusive_simp = chinese - helpers.TRADITIONAL_CHARACTERS
        if len(exclusive_trad) > len(exclusive_simp):
            return "t"
        return "s"
    return "s"


def split_lines(lines: list[str]) -> ScriptSplit:
    simp: list[str] = []
    trad: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        if route_bucket(line) == "t":
            trad.append(line)
        else:
            simp.append(line)
    return ScriptSplit(simplified_lines=simp, traditional_lines=trad)


def split_body_text(body_text: str) -> ScriptSplit:
    return split_lines(body_text.splitlines())


def join_csv_body(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
