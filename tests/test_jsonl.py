from pathlib import Path

import pytest

from janitorjav.jsonl import append_jsonl, read_jsonl, write_jsonl


def test_append_and_read_unicode_records(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_jsonl(path, {"event": "开始", "index": 1}, durable=False)
    append_jsonl(path, {"event": "完成", "index": 2}, durable=False)

    assert list(read_jsonl(path)) == [
        {"event": "开始", "index": 1},
        {"event": "完成", "index": 2},
    ]


def test_tolerates_only_truncated_tail(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"ok":1}\n{"partial":', encoding="utf-8")
    assert list(read_jsonl(path)) == [{"ok": 1}]

    path.write_text('{broken}\n{"ok":1}\n', encoding="utf-8")
    with pytest.raises(Exception):
        list(read_jsonl(path))


def test_write_replaces_file(tmp_path: Path) -> None:
    path = tmp_path / "assets.jsonl"
    path.write_text("old", encoding="utf-8")
    write_jsonl(path, [{"id": 1}, {"id": 2}])
    assert list(read_jsonl(path)) == [{"id": 1}, {"id": 2}]

