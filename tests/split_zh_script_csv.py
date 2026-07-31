"""
Split extract CSV into simplified vs traditional by line.

Uses hanzidentifier (CC-CEDICT). Not wired into the project yet — tests only.

Outputs (same folder as input):
  test_cn_s.csv  — simplified (and script-neutral / fallback)
  test_cn_t.csv  — traditional

Routing (every input data line goes to exactly one file):
  SIMPLIFIED  -> cn_s
  TRADITIONAL -> cn_t
  BOTH        -> cn_s   (shared glyphs; treat as simplified bucket)
  MIXED       -> majority of exclusive simp/trad chars; tie -> cn_s
  UNKNOWN     -> cn_s   (no Chinese / not in dictionary)

Validation:
  len(cn_s data) + len(cn_t data) == len(input data)

Run:
  pip install hanzidentifier
  $env:PYTHONUTF8 = "1"
  python .\\tests\\split_zh_script_csv.py
  python .\\tests\\split_zh_script_csv.py path\\to\\other.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_CSV = _HERE / "test_workspace" / "test.csv"
_OUT_SIMP = "test_cn_s.csv"
_OUT_TRAD = "test_cn_t.csv"
_HEADER = "text"


def _route_bucket(text: str) -> str:
    """Return 's' or 't' for one line. Must never drop a line."""
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


def _load_data_lines(path: Path) -> list[str]:
    """Load CSV-ish text column; keep original line text (strip trailing newline only)."""
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines: list[str] = []
    for line in raw.splitlines():
        cell = line.rstrip("\r\n")
        if not cell:
            continue
        if not lines and cell.strip().lower() == _HEADER:
            continue
        lines.append(cell)
    return lines


def _write_csv(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([_HEADER, *rows])
    if rows:
        body += "\n"
    else:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def split_csv(src: Path, out_dir: Path | None = None) -> dict:
    out_dir = out_dir or src.parent
    data = _load_data_lines(src)
    simp_rows: list[str] = []
    trad_rows: list[str] = []
    counts = {"s": 0, "t": 0, "SIMPLIFIED": 0, "TRADITIONAL": 0, "BOTH": 0, "MIXED": 0, "UNKNOWN": 0}

    import hanzidentifier as hz

    kind_name = {
        hz.UNKNOWN: "UNKNOWN",
        hz.TRADITIONAL: "TRADITIONAL",
        hz.SIMPLIFIED: "SIMPLIFIED",
        hz.BOTH: "BOTH",
        hz.MIXED: "MIXED",
    }

    for row in data:
        kind = hz.identify(row)
        counts[kind_name.get(kind, "UNKNOWN")] += 1
        bucket = _route_bucket(row)
        counts[bucket] += 1
        if bucket == "t":
            trad_rows.append(row)
        else:
            simp_rows.append(row)

    out_s = out_dir / _OUT_SIMP
    out_t = out_dir / _OUT_TRAD
    _write_csv(out_s, simp_rows)
    _write_csv(out_t, trad_rows)

    total_out = len(simp_rows) + len(trad_rows)
    ok = total_out == len(data)
    return {
        "src": str(src),
        "out_s": str(out_s),
        "out_t": str(out_t),
        "src_data": len(data),
        "simp_data": len(simp_rows),
        "trad_data": len(trad_rows),
        "sum_ok": ok,
        "identify_counts": {k: counts[k] for k in ("SIMPLIFIED", "TRADITIONAL", "BOTH", "MIXED", "UNKNOWN")},
    }


def main(argv: list[str]) -> int:
    try:
        import hanzidentifier  # noqa: F401
    except ImportError:
        print("missing dependency: pip install hanzidentifier", flush=True)
        return 1

    src = Path(argv[1]) if len(argv) > 1 else _DEFAULT_CSV
    if not src.is_file():
        print(f"missing csv: {src}", flush=True)
        return 1

    print(f"splitting: {src}", flush=True)
    result = split_csv(src)
    print(f"identify: {result['identify_counts']}", flush=True)
    print(
        f"src_data={result['src_data']} "
        f"simp={result['simp_data']} trad={result['trad_data']} "
        f"sum={result['simp_data'] + result['trad_data']}",
        flush=True,
    )
    print(f"wrote: {result['out_s']}", flush=True)
    print(f"wrote: {result['out_t']}", flush=True)
    if not result["sum_ok"]:
        print("ZH_SCRIPT_SPLIT_FAIL: row count mismatch", flush=True)
        return 1
    print("ZH_SCRIPT_SPLIT_OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main(sys.argv))
