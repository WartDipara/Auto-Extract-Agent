"""Tests for Feishu Bitable sheet sync (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IM_SRC = _ROOT / "apps" / "im-module" / "src"
if str(_IM_SRC) not in sys.path:
    sys.path.insert(0, str(_IM_SRC))


def _ensure_im_config():
    for p in (str(_IM_SRC),):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    cfg = sys.modules.get("config")
    if cfg is not None and "im-module" not in (cfg.__file__ or ""):
        for name in list(sys.modules):
            if name == "config" or name.startswith(
                ("courier", "sheet_sync", "feishu_bitable", "inbox_writer", "parser")
            ):
                sys.modules.pop(name, None)


def test_normalize_url_and_redo():
    _ensure_im_config()
    from feishu_bitable.schema import is_redo, is_valid_http_url, normalize_url

    assert normalize_url(" https://a.com/x.apk ") == "https://a.com/x.apk"
    assert (
        normalize_url({"link": "https://a.com/y.apk", "text": "y"})
        == "https://a.com/y.apk"
    )
    assert is_valid_http_url("https://a.com/x.apk")
    assert not is_valid_http_url("ftp://a.com/x")
    assert not is_valid_http_url("不是链接")
    assert is_redo("是")
    assert is_redo("REDO")
    assert not is_redo("maybe")


def test_decide_row_matrix(tmp_path):
    _ensure_im_config()
    from feishu_bitable.schema import SheetRow, decide_row

    seen = {"https://old.com/a.apk"}
    sheet_seen: set[str] = set()

    empty = SheetRow("r1", "", "g1", False, {})
    assert decide_row(empty, seen=seen, sheet_seen=sheet_seen).status == "invalid"

    bad = SheetRow("r2", "not-a-url", "g2", False, {})
    assert decide_row(bad, seen=seen, sheet_seen=sheet_seen).status == "invalid"

    dup = SheetRow("r3", "https://old.com/a.apk", "g3", False, {})
    assert decide_row(dup, seen=seen, sheet_seen=sheet_seen).status == "skipped_dup"

    redo = SheetRow("r4", "https://old.com/a.apk", "g4", True, {})
    assert decide_row(redo, seen=seen, sheet_seen=sheet_seen).status == "queued"

    fresh = SheetRow("r5", "https://new.com/b.apk", "g5", False, {})
    d = decide_row(fresh, seen=seen, sheet_seen=sheet_seen)
    assert d.status == "queued"
    sheet_seen.add(d.url)
    again = SheetRow("r6", "https://new.com/b.apk", "g6", False, {})
    assert (
        decide_row(again, seen=seen, sheet_seen=sheet_seen).status
        == "skipped_dup_in_sheet"
    )


def test_seen_store_corrupt_resets(tmp_path):
    _ensure_im_config()
    import sheet_sync

    path = tmp_path / "sheet_seen.json"
    path.write_text("{bad", encoding="utf-8")
    assert sheet_sync.load_seen(path) == set()
    assert path.with_suffix(".json.bak").is_file() or path.with_suffix(
        path.suffix + ".bak"
    ).is_file()


def test_sync_from_bitable_mock(tmp_path, monkeypatch):
    _ensure_im_config()
    import config
    import sheet_sync
    from feishu_bitable.client import BitableClient

    class _FakeClient(BitableClient):
        def __init__(self):
            pass

        def list_records(self, *, page_size: int = 500):
            return [
                {
                    "record_id": "rec1",
                    "fields": {"download_url": "https://a.com/1.apk", "game_name": "A"},
                },
                {
                    "record_id": "rec2",
                    "fields": {"download_url": "https://a.com/1.apk", "game_name": "A2"},
                },
                {
                    "record_id": "rec3",
                    "fields": {"download_url": "https://b.com/2.apk", "game_name": "B"},
                },
                {
                    "record_id": "rec4",
                    "fields": {"download_url": "坏链接", "game_name": "bad"},
                },
                {
                    "record_id": "rec5",
                    "fields": {
                        "download_url": "https://old.com/x.apk",
                        "game_name": "old",
                    },
                },
            ]

        def batch_update(self, records):
            self.updated = list(records)

    seen = tmp_path / "seen.json"
    sheet_sync.save_seen({"https://old.com/x.apk"}, path=seen)
    client = _FakeClient()
    result = sheet_sync.sync_from_bitable(client, seen_path=seen)
    assert result.error == ""
    assert result.queued_urls == ["https://a.com/1.apk", "https://b.com/2.apk"]
    assert result.invalid == 1
    assert result.skipped == 2  # in-sheet dup + old seen

    # seen not persisted until commit
    assert sheet_sync.load_seen(seen) == {"https://old.com/x.apk"}
    sheet_sync.commit_sync(result, seen_path=seen)
    assert "https://a.com/1.apk" in sheet_sync.load_seen(seen)
    assert "https://b.com/2.apk" in sheet_sync.load_seen(seen)
    assert getattr(client, "updated")


def test_courier_sheet_sync_command(tmp_path, monkeypatch):
    _ensure_im_config()
    import config
    import courier as courier_mod
    import sheet_sync
    from feishu_bitable.schema import RowDecision

    class _FakeChannel:
        def __init__(self):
            self.texts: list[str] = []

        def start(self, on_message):
            pass

        def reply_text(self, chat_id, text):
            self.texts.append(text)

        def send_file(self, chat_id, path):
            pass

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "SHEET_SYNC_BATCH_SIZE", 50)

    def _fake_sync():
        r = sheet_sync.SyncResult(
            queued_urls=["https://n1.com/a.apk", "https://n2.com/b.apk"],
            decisions=[
                RowDecision("r1", "https://n1.com/a.apk", "n1", "queued"),
                RowDecision("r2", "https://n2.com/b.apk", "n2", "queued"),
                RowDecision("r3", "https://old.com/x.apk", "old", "skipped_dup"),
            ],
        )
        return r

    commits: list[sheet_sync.SyncResult] = []

    def _fake_commit(result, *, seen_path=None):
        commits.append(result)
        return result

    monkeypatch.setattr(courier_mod, "sync_from_bitable", _fake_sync)
    monkeypatch.setattr(courier_mod, "commit_sync", _fake_commit)

    ch = _FakeChannel()
    c = courier_mod.Courier(ch)
    c.on_message("oc_chat", "同步")
    assert commits
    files = list(inbox.glob("im_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["get-texts"]["urls"] == [
        "https://n1.com/a.apk",
        "https://n2.com/b.apk",
    ]
    assert any("新增 2" in t for t in ch.texts)


def test_is_sync_command():
    _ensure_im_config()
    from sheet_sync import is_sync_command

    assert is_sync_command("同步")
    assert is_sync_command("SYNC")
    assert not is_sync_command("同步一下")
    assert not is_sync_command('{"get-texts":{"urls":["https://a"]}}')
