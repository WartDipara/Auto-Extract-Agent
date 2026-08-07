from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SENSITIVE_FILE = _PACKAGE_DIR / "sensitive.txt"
DEFAULT_PLACE_ALLOWLIST_FILE = _PACKAGE_DIR / "place_allowlist.txt"

_HEADER_NAMES = frozenset({"name", "word", "text", "敏感词"})
_MIN_WORD_LEN = 2

# Keep political / regime-related terms only. Drop porn, violence, drugs, gambling,
# and short game-common words (炸药 / 毒刺 / 現金 / 管理 / …) that cause false hits.
_POLITICAL_KEEP_RE = re.compile(
    r"(天安[门門]|中南海|六[四4]|六[\.．]?四|八九|学潮|學潮|民运|民運|"
    r"法[轮輪]|轮功|輪功|大法|"
    r"中共|共产|共產|共党|共黨|共匪|共铲|共鏟|退党|退黨|九评|九評|明慧|纪元|紀元|"
    r"台独|台獨|藏独|藏獨|疆独|疆獨|港独|港獨|东突|東突|达赖|達賴|刘晓波|劉曉波|"
    r"习近平|習近平|江泽民|江澤民|胡锦涛|胡錦濤|邓小平|鄧小平|毛泽东|毛澤東|"
    r"温家宝|溫家寶|李克强|李克強|彭丽媛|彭麗媛|周永康|薄熙来|薄熙來|王岐山|李鹏|李鵬|"
    r"赵紫阳|趙紫陽|胡耀邦|政变|政變|独裁|獨裁|专制|專制|暴政|维稳|維穩|"
    r"宪章|憲章|学运|學運|平反|镇反|鎮反|反右|文革|文化大革命|政治风波|政治風波|"
    r"8964|610|真善忍|大纪元|大紀元|自由门|自由門|"
    r"民阵|民陣|占中|雨伞运动|雨傘運動|反送中|"
    r"独立运动|獨立運動|民主运动|民主運動|"
    r"打台湾|打台灣|解放台湾|解放台灣|台海)",
)

_POLITICAL_SHORT = frozenset(
    {
        "六四",
        "台独",
        "台獨",
        "藏独",
        "藏獨",
        "疆独",
        "疆獨",
        "港独",
        "港獨",
        "中共",
        "共匪",
        "共党",
        "共黨",
        "退党",
        "退黨",
        "达赖",
        "達賴",
        "文革",
        "民运",
        "民運",
        "学潮",
        "學潮",
        "学运",
        "學運",
        "暴政",
        "维稳",
        "維穩",
        "九评",
        "九評",
        "明慧",
        "东突",
        "東突",
        "64",
    }
)

_cached_path: Path | None = None
_cached_allow_path: Path | None = None
_cached_words: frozenset[str] | None = None


def sensitive_words_path() -> Path:
    return DEFAULT_SENSITIVE_FILE


def place_allowlist_path() -> Path:
    return DEFAULT_PLACE_ALLOWLIST_FILE


def _load_word_lines(path: Path) -> set[str]:
    words: set[str] = set()
    if not path.is_file():
        return words
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for raw in text.splitlines():
        w = raw.strip().strip(",").strip()
        if not w or w.startswith("#") or w in _HEADER_NAMES or len(w) < _MIN_WORD_LEN:
            continue
        words.add(w)
    return words


def _is_political_word(word: str) -> bool:
    return word in _POLITICAL_SHORT or bool(_POLITICAL_KEEP_RE.search(word))


def load_place_allowlist(path: Path | None = None) -> frozenset[str]:
    target = Path(path) if path is not None else DEFAULT_PLACE_ALLOWLIST_FILE
    return frozenset(_load_word_lines(target))


def load_sensitive_words(path: Path | None = None) -> frozenset[str]:
    global _cached_path, _cached_allow_path, _cached_words
    target = Path(path) if path is not None else DEFAULT_SENSITIVE_FILE
    allow_path = DEFAULT_PLACE_ALLOWLIST_FILE
    if (
        _cached_words is not None
        and _cached_path == target
        and _cached_allow_path == allow_path
    ):
        return _cached_words
    words = {w for w in _load_word_lines(target) if _is_political_word(w)}
    words -= _load_word_lines(allow_path)
    _cached_path = target
    _cached_allow_path = allow_path
    _cached_words = frozenset(words)
    return _cached_words


def clear_sensitive_words_cache() -> None:
    global _cached_path, _cached_allow_path, _cached_words
    _cached_path = None
    _cached_allow_path = None
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
