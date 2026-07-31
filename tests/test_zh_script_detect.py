"""
Local smoke: classify each CSV line as simplified / traditional Chinese.

Uses hanzidentifier (CC-CEDICT based). Run:

  pip install hanzidentifier
  cd D:\\smwl\\Auto-Extract-Agent
  $env:PYTHONUTF8 = "1"
  python .\\tests\\test_zh_script_detect.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CSV = _HERE / "test_workspace" / "text.csv"

_LABEL = {
    "UNKNOWN": "unknown",
    "BOTH": "both(ambiguous)",
    "TRADITIONAL": "traditional",
    "SIMPLIFIED": "simplified",
    "MIXED": "mixed",
}


def _label_name(value) -> str:
    import hanzidentifier as hz

    for name in ("UNKNOWN", "BOTH", "TRADITIONAL", "SIMPLIFIED", "MIXED"):
        if value is getattr(hz, name):
            return _LABEL[name]
    return str(value)


def classify_line(text: str) -> dict:
    """Return script classification for one line of Chinese text."""
    import hanzidentifier as hz

    kind = hz.identify(text)
    return {
        "text": text,
        "kind": _label_name(kind),
        "is_simplified": hz.is_simplified(text),
        "is_traditional": hz.is_traditional(text),
    }


def load_csv_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines: list[str] = []
    for line in raw.splitlines():
        cell = line.strip()
        if not cell or cell.lower() == "text":
            continue
        lines.append(cell)
    return lines


def main() -> int:
    try:
        import hanzidentifier  # noqa: F401
    except ImportError:
        print("missing dependency: pip install hanzidentifier", flush=True)
        return 1

    if not _CSV.is_file():
        print(f"missing csv: {_CSV}", flush=True)
        return 1

    rows = [classify_line(line) for line in load_csv_lines(_CSV)]
    for i, row in enumerate(rows, 1):
        print(
            f"[{i}] kind={row['kind']} "
            f"simp={row['is_simplified']} trad={row['is_traditional']}\n"
            f"    {row['text']}",
            flush=True,
        )

    # Expected for tests/test_workspace/text.csv
    assert len(rows) >= 2, "need at least 2 sample lines"
    assert rows[0]["kind"] == "traditional", rows[0]
    assert rows[0]["is_traditional"] is True
    assert rows[1]["kind"] == "simplified", rows[1]
    assert rows[1]["is_simplified"] is True
    print("ZH_SCRIPT_DETECT_OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
