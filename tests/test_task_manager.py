from pathlib import Path

from janitorjav.jsonl import append_jsonl
from janitorjav.models import ReviewStatus
from janitorjav.ocr import OCRLine
from janitorjav.task_manager import TaskManager


class EmptyOCR:
    name = "empty"

    def recognize(self, image_paths: list[Path]) -> list[list[OCRLine]]:
        return [[] for _ in image_paths]


def test_quarantine_and_restore_round_trip(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    asset_dir = scan / "2026" / "ABC-123"
    asset_dir.mkdir(parents=True)
    source = asset_dir / "ABC-123.mp4"
    source.write_bytes(b"video")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)
    stat = source.stat()
    record = {
        "asset_id": "asset-1",
        "directory": str(asset_dir),
        "group_key": "ABC-123",
        "group_type": "single",
        "is_vr": False,
        "videos": [],
        "files": [str(source)],
        "tags": ["url_detected"],
        "review_status": ReviewStatus.READY_TO_QUARANTINE.value,
        "snapshots": {str(source): {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}},
    }
    append_jsonl(task.workspace / "assets.jsonl", record, durable=False)

    operations = manager.quarantine_assets(task.task_id, ["asset-1"])
    assert manager.assets(task.task_id, tagged_only=False)["items"][0]["restore_mode"] == "asset"
    target = task.quarantine_root / "2026" / "ABC-123" / "ABC-123.mp4"
    assert operations[0]["status"] == "completed"
    assert not source.exists()
    assert target.read_bytes() == b"video"

    operations = manager.restore_assets(task.task_id, ["asset-1"])
    assert manager.assets(task.task_id, tagged_only=False)["items"][0]["restore_mode"] is None
    assert operations[0]["status"] == "completed"
    assert source.read_bytes() == b"video"
    assert not target.exists()


def test_source_change_blocks_quarantine(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    source = scan / "ABC-123.mp4"
    source.write_bytes(b"new")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)
    record = {
        "asset_id": "asset-1",
        "files": [str(source)],
        "tags": [],
        "review_status": ReviewStatus.READY_TO_QUARANTINE.value,
        "snapshots": {str(source): {"size": 1, "mtime_ns": 1}},
    }
    append_jsonl(task.workspace / "assets.jsonl", record, durable=False)
    operation = manager.quarantine_assets(task.task_id, ["asset-1"])[0]
    assert operation["status"] == "failed"
    assert "changed since scan" in operation["error"]
    assert source.exists()
    latest = manager.assets(task.task_id, tagged_only=False)["items"][0]
    assert "source_changed_since_scan" in latest["tags"]


def test_whole_directory_quarantine_includes_unassigned_and_restores(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    directory = scan / "2026" / "ABC-123"
    directory.mkdir(parents=True)
    first = directory / "ABC-123-A.mp4"
    second = directory / "ABC-123-B.mp4"
    extra = directory / "notes.txt"
    junk = directory / "Thumbs.db"
    for path in (first, second, extra, junk):
        path.write_text(path.name, encoding="utf-8")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)

    for index, source in enumerate((first, second), start=1):
        stat = source.stat()
        append_jsonl(
            task.workspace / "assets.jsonl",
            {
                "asset_id": f"asset-{index}",
                "directory": str(directory),
                "group_key": source.stem,
                "files": [str(source)],
                "tags": ["url_detected"],
                "review_status": ReviewStatus.READY_TO_QUARANTINE.value,
                "snapshots": {str(source): {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}},
            },
            durable=False,
        )

    listed = manager.assets(task.task_id, tagged_only=False)["items"]
    effect = listed[0]["directory_effect"]
    assert effect["all_assets_ready"] is True
    assert effect["effectively_empty"] is False
    assert effect["remaining_entries"] == [str(extra)]
    assert effect["system_entries"] == [str(junk)]

    operation = manager.quarantine_directory(task.task_id, directory)
    assert manager.assets(task.task_id, tagged_only=False)["items"][0]["restore_mode"] == "directory"
    quarantined = task.quarantine_root / "2026" / "ABC-123"
    assert operation["status"] == "completed"
    assert not directory.exists()
    assert (quarantined / "notes.txt").exists()
    assert (quarantined / "Thumbs.db").exists()

    operation = manager.restore_directory(task.task_id, directory)
    assert manager.assets(task.task_id, tagged_only=False)["items"][0]["restore_mode"] is None
    assert operation["status"] == "completed"
    assert extra.exists()
    assert junk.exists()
    assert not quarantined.exists()
