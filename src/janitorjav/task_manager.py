from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jsonl import append_jsonl, read_jsonl
from .media import FFmpegTools
from .models import ReviewStatus
from .naming import DEFAULT_VIDEO_EXTENSIONS, discover_asset_groups
from .ocr import OCREngine
from .paths import quarantine_target, validate_or_create_quarantine
from .pipeline import ScanPipeline, ScanPipelineConfig, stable_asset_id
from .serialization import group_to_dict, snapshot_paths
from .scoring import evidence_score


IGNORED_SYSTEM_NAMES = frozenset(
    {
        ".ds_store",
        "thumbs.db",
        "desktop.ini",
        ".spotlight-v100",
        ".trashes",
        ".fseventsd",
        "system volume information",
        "$recycle.bin",
    }
)


def default_workspace_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "JanitorJAV" / "tasks"
    return Path.home() / ".local" / "share" / "JanitorJAV" / "tasks"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class TaskState:
    task_id: str
    scan_root: Path
    quarantine_root: Path
    workspace: Path
    video_workers: int = 1
    status: str = "created"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None
    discovered: int = 0
    completed: int = 0
    tagged: int = 0
    errors: int = 0
    current_file: str | None = None
    error: str | None = None
    stop_requested: bool = False
    pause_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scan_root": str(self.scan_root),
            "quarantine_root": str(self.quarantine_root),
            "workspace": str(self.workspace),
            "video_workers": self.video_workers,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "discovered": self.discovered,
            "completed": self.completed,
            "tagged": self.tagged,
            "errors": self.errors,
            "current_file": self.current_file,
            "error": self.error,
            "stop_requested": self.stop_requested,
            "pause_requested": self.pause_requested,
        }


class TaskManager:
    def __init__(
        self,
        ocr_engine: OCREngine,
        workspace_root: Path | None = None,
        *,
        frame_workers: int = 4,
        video_workers: int = 1,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.frame_workers = max(1, frame_workers)
        self.default_video_workers = max(1, min(8, video_workers))
        self.workspace_root = workspace_root or default_workspace_root()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, TaskState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._load_tasks()

    def create_task(self, scan_root: Path, *, video_workers: int | None = None) -> TaskState:
        scan_root = scan_root.resolve()
        selected_workers = self.default_video_workers if video_workers is None else video_workers
        if not 1 <= selected_workers <= 8:
            raise ValueError("Video workers must be between 1 and 8")
        quarantine = validate_or_create_quarantine(scan_root)
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        workspace = self.workspace_root / task_id
        workspace.mkdir(parents=True)
        task = TaskState(task_id, scan_root, quarantine, workspace, video_workers=selected_workers)
        with self._lock:
            self._tasks[task_id] = task
            self._save_task(task)
        return task

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in sorted(self._tasks.values(), key=lambda x: x.created_at, reverse=True)]

    def get_task(self, task_id: str) -> TaskState:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as error:
                raise KeyError(f"Unknown task: {task_id}") from error

    def start_task(self, task_id: str) -> TaskState:
        task = self.get_task(task_id)
        with self._lock:
            if task.status == "paused":
                task.pause_requested = False
                task.status = "running"
                self._save_task(task)
                thread = self._threads.get(task_id)
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(target=self._scan, args=(task,), daemon=True)
                    self._threads[task_id] = thread
                    thread.start()
                return task
            if task.status == "running":
                return task
            if task.status not in {"created", "cancelled", "failed"}:
                raise ValueError(f"Task cannot start from status {task.status}")
            task.stop_requested = False
            task.status = "running"
            task.started_at = task.started_at or _now()
            task.error = None
            self._save_task(task)
            thread = threading.Thread(target=self._scan, args=(task,), daemon=True)
            self._threads[task_id] = thread
            thread.start()
        return task

    def pause_task(self, task_id: str) -> TaskState:
        task = self.get_task(task_id)
        if task.status != "running":
            raise ValueError(f"Task cannot pause from status {task.status}")
        task.pause_requested = True
        self._save_task(task)
        return task

    def cancel_task(self, task_id: str) -> TaskState:
        task = self.get_task(task_id)
        task.stop_requested = True
        thread = self._threads.get(task_id)
        if task.status == "paused" and (thread is None or not thread.is_alive()):
            task.status = "cancelled"
            task.stop_requested = False
        self._save_task(task)
        return task

    def delete_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status in {"running", "paused"}:
            raise ValueError("Running or paused tasks cannot be deleted")
        with self._lock:
            self._tasks.pop(task_id, None)
        shutil.rmtree(task.workspace)

    def assets(
        self,
        task_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        tagged_only: bool = True,
        tag: str | None = None,
        status: str | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        ocr_keyword: str | None = None,
    ) -> dict[str, Any]:
        task = self.get_task(task_id)
        records = list(read_jsonl(task.workspace / "assets.jsonl"))
        latest = {record["asset_id"]: record for record in records}
        restore_modes: dict[str, str] = {}
        for operation in read_jsonl(task.workspace / "operations.jsonl"):
            if operation.get("status") != "completed":
                continue
            operation_type = operation.get("operation_type", "quarantine")
            if operation_type == "quarantine" and operation.get("asset_id"):
                restore_modes[operation["asset_id"]] = "asset"
            elif operation_type == "restore" and operation.get("asset_id"):
                restore_modes.pop(operation["asset_id"], None)
            elif operation_type == "quarantine_directory":
                for asset_id in operation.get("asset_ids", []):
                    restore_modes[asset_id] = "directory"
            elif operation_type == "restore_directory":
                for asset_id in operation.get("asset_ids", []):
                    restore_modes.pop(asset_id, None)
        values = list(latest.values())
        for record in values:
            score, label, summary = evidence_score(record)
            record["risk_score"] = score
            record["risk_label"] = label
            record["evidence_summary"] = summary
        if tagged_only:
            values = [record for record in values if record.get("tags")]
        if tag:
            values = [record for record in values if tag in record.get("tags", [])]
        if min_duration is not None:
            values = [record for record in values if (record.get("total_duration_seconds") or 0) >= min_duration]
        if max_duration is not None:
            values = [record for record in values if (record.get("total_duration_seconds") or float("inf")) <= max_duration]
        if min_width is not None:
            values = [record for record in values if (record.get("max_width") or 0) >= min_width]
        if min_height is not None:
            values = [record for record in values if (record.get("max_height") or 0) >= min_height]
        if ocr_keyword:
            keyword = ocr_keyword.casefold()
            values = [record for record in values if _record_contains_ocr(record, keyword)]
        status_counts = {
            review_status.value: sum(
                record.get("review_status") == review_status.value for record in values
            )
            for review_status in ReviewStatus
        }
        if status:
            values = [record for record in values if record.get("review_status") == status]
        values.sort(
            key=lambda record: (
                -record.get("risk_score", 0),
                record.get("directory", "").casefold(),
                record.get("group_key", "").casefold(),
            )
        )
        total = len(values)
        start = max(0, (page - 1) * page_size)
        page_values = values[start : start + page_size]
        by_directory: dict[str, list[dict[str, Any]]] = {}
        for record in latest.values():
            by_directory.setdefault(record.get("directory", ""), []).append(record)
        for record in page_values:
            directory_value = record.get("directory", str(task.scan_root))
            record["restore_mode"] = restore_modes.get(record["asset_id"])
            record["directory_effect"] = _directory_effect(
                Path(directory_value), by_directory.get(record.get("directory", ""), [])
            )
        return {
            "items": page_values,
            "total": total,
            "page": page,
            "page_size": page_size,
            "status_counts": status_counts,
        }

    def set_review_status(self, task_id: str, asset_ids: list[str], status: ReviewStatus) -> None:
        task = self.get_task(task_id)
        latest = self._latest_assets(task)
        for asset_id in asset_ids:
            record = latest.get(asset_id)
            if record is None:
                continue
            record = dict(record)
            record["review_status"] = status.value
            record["updated_at"] = _now()
            append_jsonl(task.workspace / "assets.jsonl", record)

    def matching_asset_ids(
        self,
        task_id: str,
        *,
        min_score: int | None = None,
        tagged_only: bool = True,
        tag: str | None = None,
        status: str | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        ocr_keyword: str | None = None,
    ) -> list[str]:
        task = self.get_task(task_id)
        values = list(self._latest_assets(task).values())
        result: list[str] = []
        for record in values:
            score, _, _ = evidence_score(record)
            if min_score is not None and score < min_score:
                continue
            if tagged_only and not record.get("tags"):
                continue
            if tag and tag not in record.get("tags", []):
                continue
            if status and record.get("review_status") != status:
                continue
            duration = record.get("total_duration_seconds")
            if min_duration is not None and (duration or 0) < min_duration:
                continue
            if max_duration is not None and (duration or float("inf")) > max_duration:
                continue
            if min_width is not None and (record.get("max_width") or 0) < min_width:
                continue
            if min_height is not None and (record.get("max_height") or 0) < min_height:
                continue
            if ocr_keyword and not _record_contains_ocr(record, ocr_keyword.casefold()):
                continue
            result.append(record["asset_id"])
        return result

    def quarantine_ready_assets(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        ready_ids = [
            asset_id
            for asset_id, record in self._latest_assets(task).items()
            if record.get("review_status") == ReviewStatus.READY_TO_QUARANTINE.value
        ]
        return self.quarantine_assets(task_id, ready_ids)

    def quarantine_assets(self, task_id: str, asset_ids: list[str]) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        latest = self._latest_assets(task)
        results: list[dict[str, Any]] = []
        for asset_id in asset_ids:
            record = latest.get(asset_id)
            if not record or record.get("review_status") != ReviewStatus.READY_TO_QUARANTINE.value:
                continue
            result = self._move_record(task, record)
            results.append(result)
        return results

    def restore_assets(self, task_id: str, asset_ids: list[str]) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        latest = self._latest_assets(task)
        operations = list(read_jsonl(task.workspace / "operations.jsonl"))
        results: list[dict[str, Any]] = []
        for asset_id in asset_ids:
            record = latest.get(asset_id)
            if not record or record.get("review_status") != ReviewStatus.QUARANTINED.value:
                continue
            source_operation = next(
                (
                    item
                    for item in reversed(operations)
                    if item.get("asset_id") == asset_id
                    and item.get("operation_type", "quarantine") == "quarantine"
                    and item.get("status") == "completed"
                ),
                None,
            )
            if source_operation is None:
                continue
            result = self._restore_record(task, record, source_operation)
            results.append(result)
        return results

    def quarantine_directory(self, task_id: str, directory: Path) -> dict[str, Any]:
        task = self.get_task(task_id)
        directory = directory.resolve()
        if not _is_inside(directory, task.scan_root.resolve()):
            raise ValueError("Directory is outside scan root")
        records = [
            record
            for record in self._latest_assets(task).values()
            if Path(record.get("directory", "")).resolve() == directory
        ]
        if not records or not all(
            record.get("review_status") == ReviewStatus.READY_TO_QUARANTINE.value
            for record in records
        ):
            raise ValueError("All assets in the directory must be ready to quarantine")
        for record in records:
            _validate_snapshots(record)
        target = quarantine_target(task.scan_root, task.quarantine_root, directory)
        operation = {
            "operation_type": "quarantine_directory",
            "asset_ids": [record["asset_id"] for record in records],
            "source": str(directory),
            "target": str(target),
            "started_at": _now(),
            "status": "running",
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise RuntimeError(f"Quarantine target exists: {target}")
            directory.replace(target)
            operation["status"] = "completed"
            status = ReviewStatus.QUARANTINED
        except Exception as error:
            operation["status"] = "failed"
            operation["error"] = str(error)
            status = ReviewStatus.QUARANTINE_FAILED
        operation["completed_at"] = _now()
        append_jsonl(task.workspace / "operations.jsonl", operation)
        for record in records:
            updated = dict(record)
            updated["review_status"] = status.value
            updated["updated_at"] = _now()
            append_jsonl(task.workspace / "assets.jsonl", updated)
        return operation

    def restore_directory(self, task_id: str, directory: Path) -> dict[str, Any]:
        task = self.get_task(task_id)
        directory = directory.resolve()
        source_operation = next(
            (
                item
                for item in reversed(list(read_jsonl(task.workspace / "operations.jsonl")))
                if item.get("operation_type") == "quarantine_directory"
                and Path(item.get("source", "")).resolve() == directory
                and item.get("status") == "completed"
            ),
            None,
        )
        if source_operation is None:
            raise ValueError("Completed directory quarantine operation not found")
        quarantine_path = Path(source_operation["target"])
        operation = {
            "operation_type": "restore_directory",
            "asset_ids": source_operation["asset_ids"],
            "source": str(quarantine_path),
            "target": str(directory),
            "started_at": _now(),
            "status": "running",
        }
        try:
            if directory.exists():
                raise RuntimeError(f"Restore target exists: {directory}")
            directory.parent.mkdir(parents=True, exist_ok=True)
            quarantine_path.replace(directory)
            _prune_empty_parents(quarantine_path.parent, stop_at=task.quarantine_root)
            operation["status"] = "completed"
            status = ReviewStatus.RESTORED
        except Exception as error:
            operation["status"] = "failed"
            operation["error"] = str(error)
            status = ReviewStatus.QUARANTINE_FAILED
        operation["completed_at"] = _now()
        append_jsonl(task.workspace / "operations.jsonl", operation)
        latest = self._latest_assets(task)
        for asset_id in source_operation["asset_ids"]:
            record = latest.get(asset_id)
            if record:
                updated = dict(record)
                updated["review_status"] = status.value
                updated["updated_at"] = _now()
                append_jsonl(task.workspace / "assets.jsonl", updated)
        return operation

    def _move_record(self, task: TaskState, record: dict[str, Any]) -> dict[str, Any]:
        files = [Path(value) for value in record.get("files", [])]
        expected = record.get("snapshots", {})
        operation = {"asset_id": record["asset_id"], "operation_type": "quarantine", "started_at": _now(), "files": [], "status": "running"}
        moved: list[tuple[Path, Path]] = []
        try:
            for source in files:
                stat = source.stat()
                snapshot = expected.get(str(source))
                if not snapshot or stat.st_size != snapshot["size"] or stat.st_mtime_ns != snapshot["mtime_ns"]:
                    raise RuntimeError(f"Source changed since scan: {source}")
            for source in files:
                target = quarantine_target(task.scan_root, task.quarantine_root, source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError(f"Quarantine target exists: {target}")
                source.replace(target)
                moved.append((source, target))
                operation["files"].append({"source": str(source), "target": str(target), "status": "moved"})
            operation["status"] = "completed"
            status = ReviewStatus.QUARANTINED
        except Exception as error:
            operation["error"] = str(error)
            operation["status"] = "failed"
            for source, target in reversed(moved):
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    target.replace(source)
                except OSError as rollback_error:
                    operation.setdefault("rollback_errors", []).append(str(rollback_error))
            status = ReviewStatus.QUARANTINE_FAILED
        operation["completed_at"] = _now()
        append_jsonl(task.workspace / "operations.jsonl", operation)
        updated = dict(record)
        updated["review_status"] = status.value
        if status is ReviewStatus.QUARANTINE_FAILED and "changed since scan" in operation.get("error", "").casefold():
            updated["tags"] = sorted(set(updated.get("tags", [])) | {"source_changed_since_scan"})
        updated["updated_at"] = _now()
        append_jsonl(task.workspace / "assets.jsonl", updated)
        return operation

    def _restore_record(
        self,
        task: TaskState,
        record: dict[str, Any],
        source_operation: dict[str, Any],
    ) -> dict[str, Any]:
        operation = {"asset_id": record["asset_id"], "operation_type": "restore", "started_at": _now(), "files": [], "status": "running"}
        moved: list[tuple[Path, Path]] = []
        try:
            pairs = [(Path(item["target"]), Path(item["source"])) for item in source_operation["files"]]
            for quarantine_path, original_path in pairs:
                if not quarantine_path.is_file():
                    raise RuntimeError(f"Quarantined file is missing: {quarantine_path}")
                if original_path.exists():
                    raise RuntimeError(f"Restore target exists: {original_path}")
            for quarantine_path, original_path in pairs:
                original_path.parent.mkdir(parents=True, exist_ok=True)
                quarantine_path.replace(original_path)
                moved.append((quarantine_path, original_path))
                operation["files"].append({"source": str(quarantine_path), "target": str(original_path), "status": "restored"})
            for quarantine_path, _ in pairs:
                _prune_empty_parents(quarantine_path.parent, stop_at=task.quarantine_root)
            operation["status"] = "completed"
            status = ReviewStatus.RESTORED
        except Exception as error:
            operation["error"] = str(error)
            operation["status"] = "failed"
            for quarantine_path, original_path in reversed(moved):
                try:
                    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
                    original_path.replace(quarantine_path)
                except OSError as rollback_error:
                    operation.setdefault("rollback_errors", []).append(str(rollback_error))
            status = ReviewStatus.QUARANTINE_FAILED
        operation["completed_at"] = _now()
        append_jsonl(task.workspace / "operations.jsonl", operation)
        updated = dict(record)
        updated["review_status"] = status.value
        updated["updated_at"] = _now()
        append_jsonl(task.workspace / "assets.jsonl", updated)
        return operation

    def _scan(self, task: TaskState) -> None:
        try:
            groups = []
            for root, directories, files in os.walk(task.scan_root, followlinks=False):
                directories[:] = [
                    name
                    for name in directories
                    if not (Path(root) / name).is_symlink()
                    and name.casefold() != task.quarantine_root.name.casefold()
                    and name.casefold() not in IGNORED_SYSTEM_NAMES
                    and not name.casefold().startswith("._")
                ]
                if any(Path(name).suffix.casefold() in DEFAULT_VIDEO_EXTENSIONS for name in files):
                    groups.extend(discover_asset_groups(Path(root)))
            task.discovered = len(groups)
            self._save_task(task)
            completed_assets = self._latest_assets(task)
            completed_ids = set(completed_assets)
            task.completed = len(completed_ids)
            task.tagged = sum(bool(record.get("tags")) for record in completed_assets.values())
            pipeline = ScanPipeline(
                FFmpegTools(),
                self.ocr_engine,
                task.workspace / "evidence",
                config=ScanPipelineConfig(frame_workers=self.frame_workers),
            )
            pending_groups = [group for group in groups if stable_asset_id(group) not in completed_ids]
            for batch_start in range(0, len(pending_groups), task.video_workers):
                if task.stop_requested:
                    task.status = "cancelled"
                    task.stop_requested = False
                    break
                while task.pause_requested and not task.stop_requested:
                    task.status = "paused"
                    self._save_task(task)
                    time.sleep(0.25)
                if task.stop_requested:
                    task.status = "cancelled"
                    task.stop_requested = False
                    break
                task.status = "running"
                batch = pending_groups[batch_start : batch_start + task.video_workers]
                task.current_file = " | ".join(
                    str(group.directory / group.group_key) for group in batch
                )
                self._save_task(task)
                with ThreadPoolExecutor(
                    max_workers=len(batch), thread_name_prefix="janitorjav-video"
                ) as executor:
                    futures = [executor.submit(pipeline.scan_group, group) for group in batch]
                    for group, future in zip(batch, futures, strict=True):
                        future.result()
                        record = group_to_dict(group, asset_id=stable_asset_id(group))
                        record["snapshots"] = snapshot_paths(record)
                        record["scanned_at"] = _now()
                        append_jsonl(task.workspace / "assets.jsonl", record)
                        task.completed += 1
                        if record["tags"]:
                            task.tagged += 1
                        self._save_task(task)
            else:
                task.status = "completed"
                task.completed_at = _now()
        except Exception as error:
            task.status = "failed"
            task.error = str(error)
            task.errors += 1
        finally:
            task.current_file = None
            self._save_task(task)

    def _latest_assets(self, task: TaskState) -> dict[str, dict[str, Any]]:
        return {record["asset_id"]: record for record in read_jsonl(task.workspace / "assets.jsonl")}

    def _save_task(self, task: TaskState) -> None:
        temporary = task.workspace / "task.json.tmp"
        temporary.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(task.workspace / "task.json")

    def _load_tasks(self) -> None:
        for path in self.workspace_root.glob("*/task.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                task = TaskState(
                    task_id=payload["task_id"],
                    scan_root=Path(payload["scan_root"]),
                    quarantine_root=Path(payload["quarantine_root"]),
                    workspace=Path(payload["workspace"]),
                    video_workers=payload.get("video_workers", self.default_video_workers),
                    status=payload["status"],
                    created_at=payload["created_at"],
                    started_at=payload.get("started_at"),
                    completed_at=payload.get("completed_at"),
                    discovered=payload.get("discovered", 0),
                    completed=payload.get("completed", 0),
                    tagged=payload.get("tagged", 0),
                    errors=payload.get("errors", 0),
                    current_file=payload.get("current_file"),
                    error=payload.get("error"),
                    stop_requested=payload.get("stop_requested", False),
                    pause_requested=payload.get("pause_requested", False),
                )
                if task.status == "running":
                    task.status = "cancelled"
                self._tasks[task.task_id] = task
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue


def _prune_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path
    stop_at = stop_at.resolve()
    while current.resolve() != stop_at:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_snapshots(record: dict[str, Any]) -> None:
    expected = record.get("snapshots", {})
    for value in record.get("files", []):
        path = Path(value)
        stat = path.stat()
        snapshot = expected.get(str(path))
        if not snapshot or stat.st_size != snapshot["size"] or stat.st_mtime_ns != snapshot["mtime_ns"]:
            raise RuntimeError(f"Source changed since scan: {path}")


def _is_system_entry(path: Path) -> bool:
    name = path.name.casefold()
    return name in IGNORED_SYSTEM_NAMES or name.startswith("._")


def _record_contains_ocr(record: dict[str, Any], keyword: str) -> bool:
    return any(
        keyword in str(frame.get("ocr_text", "")).casefold()
        for video in record.get("videos", [])
        for frame in video.get("frames", [])
    )


def _directory_effect(directory: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    all_ready = bool(records) and all(
        record.get("review_status") == ReviewStatus.READY_TO_QUARANTINE.value
        for record in records
    )
    known = {
        str(Path(value).resolve()).casefold()
        for record in records
        for value in record.get("files", [])
    }
    remaining: list[str] = []
    system: list[str] = []
    if directory.is_dir():
        try:
            for entry in directory.iterdir():
                if str(entry.resolve()).casefold() in known:
                    continue
                (system if _is_system_entry(entry) else remaining).append(str(entry))
        except OSError:
            pass
    return {
        "all_assets_ready": all_ready,
        "effectively_empty": all_ready and not remaining,
        "remaining_entries": sorted(remaining, key=str.casefold),
        "system_entries": sorted(system, key=str.casefold),
    }
