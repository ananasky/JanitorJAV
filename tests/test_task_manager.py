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
    target = task.quarantine_root / "2026" / "ABC-123" / "ABC-123.mp4"
    assert operations[0]["status"] == "completed"
    assert not source.exists()
    assert target.read_bytes() == b"video"

    operations = manager.restore_assets(task.task_id, ["asset-1"])
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

