import threading
import time
from pathlib import Path

import janitorjav.task_manager as task_manager_module
from janitorjav.jsonl import append_jsonl
from janitorjav.models import ReviewStatus
from janitorjav.ocr import OCRLine
from janitorjav.task_manager import TaskManager


class EmptyOCR:
    name = "empty"

    def recognize(self, image_paths: list[Path]) -> list[list[OCRLine]]:
        return [[] for _ in image_paths]


def test_files_only_scan_preserves_groups_without_media_processing(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("File-only mode must not probe, extract or OCR")

    monkeypatch.setattr(task_manager_module.FFmpegTools, "probe", forbidden)
    monkeypatch.setattr(EmptyOCR, "recognize", forbidden)
    scan = tmp_path / "JAV"
    scan.mkdir()
    for stem in ("ABC-CD1", "ABC-CD2", "DEF"):
        (scan / f"{stem}.mp4").write_bytes(b"not a video")
        (scan / f"{stem}.nfo").write_text("info")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan, files_only=True)
    manager.start_task(task.task_id)
    manager._threads[task.task_id].join(timeout=5)
    assert task.status == "completed"
    items = manager.assets(task.task_id, tagged_only=False)["items"]
    assert len(items) == 2
    assert sum(len(item["files"]) for item in items) == 6
    assert all(not video["frames"] for item in items for video in item["videos"])
    reloaded = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    assert reloaded.get_task(task.task_id).files_only is True


def test_task_video_workers_are_persisted(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    workspace = tmp_path / "tasks"
    manager = TaskManager(EmptyOCR(), workspace_root=workspace)
    task = manager.create_task(scan, video_workers=6)

    reloaded = TaskManager(EmptyOCR(), workspace_root=workspace)

    assert reloaded.get_task(task.task_id).video_workers == 6


def test_task_processes_multiple_videos_in_parallel(tmp_path: Path, monkeypatch) -> None:
    class TrackingPipeline:
        active = 0
        max_active = 0
        lock = threading.Lock()

        def __init__(self, *args, **kwargs) -> None:
            pass

        def scan_group(self, group):
            with self.lock:
                type(self).active += 1
                type(self).max_active = max(type(self).max_active, type(self).active)
            time.sleep(0.03)
            with self.lock:
                type(self).active -= 1
            return group

    monkeypatch.setattr(task_manager_module, "ScanPipeline", TrackingPipeline)
    scan = tmp_path / "JAV"
    for index in range(6):
        directory = scan / f"ABC-{index:03d} title"
        directory.mkdir(parents=True)
        (directory / f"ABC-{index:03d}.mp4").write_bytes(b"video")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan, video_workers=3)

    manager.start_task(task.task_id)
    for _ in range(200):
        if task.status == "completed":
            break
        time.sleep(0.01)

    assert task.status == "completed"
    assert task.completed == 6
    assert TrackingPipeline.max_active == 3


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


def test_quarantine_job_reports_progress_and_completion(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    asset_dir = scan / "ABC-123"
    asset_dir.mkdir(parents=True)
    source = asset_dir / "ABC-123.mp4"
    source.write_bytes(b"video")
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)
    stat = source.stat()
    append_jsonl(
        task.workspace / "assets.jsonl",
        {
            "asset_id": "asset-1",
            "directory": str(asset_dir),
            "group_key": "ABC-123",
            "videos": [],
            "files": [str(source)],
            "tags": ["url_detected"],
            "review_status": ReviewStatus.READY_TO_QUARANTINE.value,
            "snapshots": {str(source): {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}},
        },
        durable=False,
    )

    started = manager.start_quarantine_job(task.task_id, ["asset-1"])
    for _ in range(100):
        job = manager.get_quarantine_job(task.task_id, started["job_id"])
        if job["status"] != "running":
            break
        time.sleep(0.01)

    assert job["status"] == "completed"
    assert job["total"] == job["completed"] == job["succeeded"] == 1
    assert job["failed"] == 0
    assert job["failed_items"] == []
    assert job["completed_asset_ids"] == ["asset-1"]


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


def test_asset_listing_returns_review_status_counts(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)
    for index, status in enumerate(("pending", "keep", "ready_to_quarantine")):
        append_jsonl(
            task.workspace / "assets.jsonl",
            {
                "asset_id": str(index),
                "directory": str(scan),
                "group_key": str(index),
                "videos": [],
                "files": [],
                "tags": ["url_detected"],
                "review_status": status,
            },
            durable=False,
        )

    result = manager.assets(task.task_id, status="pending")

    assert result["total"] == 1
    assert result["status_counts"]["pending"] == 1
    assert result["status_counts"]["keep"] == 1
    assert result["status_counts"]["ready_to_quarantine"] == 1


def test_matching_asset_ids_filters_score_across_pages(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    task = manager.create_task(scan)
    for asset_id, text in (("high", "澳门娱乐城\nexample.com"), ("low", "example.com")):
        append_jsonl(
            task.workspace / "assets.jsonl",
            {
                "asset_id": asset_id,
                "directory": str(scan),
                "group_key": asset_id,
                "tags": ["url_detected"],
                "review_status": "pending",
                "total_duration_seconds": 120 if asset_id == "high" else 3600,
                "max_width": 640 if asset_id == "high" else 1920,
                "max_height": 480 if asset_id == "high" else 1080,
                "videos": [{"frames": [{"ocr_text": text, "matches": [{"type": "domain_like", "normalized_text": "example.com", "confidence": 0.95}]}]}],
            },
            durable=False,
        )

    assert manager.matching_asset_ids(task.task_id, min_score=200, status="pending") == ["high"]
    assert manager.matching_asset_ids(task.task_id, ocr_keyword="娱乐城", status="pending") == ["high"]
    assert manager.assets(task.task_id, tagged_only=False, ocr_keyword="娱乐城")["total"] == 1
    assert manager.assets(task.task_id, tagged_only=False, max_duration=300)["total"] == 1
    assert manager.assets(task.task_id, tagged_only=False, max_width=1280, max_height=720)["total"] == 1
    assert manager.assets(task.task_id, tagged_only=False, path_query="high")["total"] == 1
    assert manager.matching_asset_ids(task.task_id, path_query="HIGH", status="pending") == ["high"]


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
