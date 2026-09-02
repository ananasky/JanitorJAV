from __future__ import annotations

import json
import os
import threading
import time
import uuid
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
from .pipeline import ScanPipeline, stable_asset_id
from .serialization import group_to_dict, snapshot_paths


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scan_root": str(self.scan_root),
            "quarantine_root": str(self.quarantine_root),
            "workspace": str(self.workspace),
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
        }


class TaskManager:
    def __init__(self, ocr_engine: OCREngine, workspace_root: Path | None = None) -> None:
        self.ocr_engine = ocr_engine
        self.workspace_root = workspace_root or default_workspace_root()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, TaskState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._load_tasks()

    def create_task(self, scan_root: Path) -> TaskState:
        scan_root = scan_root.resolve()
        quarantine = validate_or_create_quarantine(scan_root)
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        workspace = self.workspace_root / task_id
        workspace.mkdir(parents=True)
        task = TaskState(task_id, scan_root, quarantine, workspace)
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

    def cancel_task(self, task_id: str) -> TaskState:
        task = self.get_task(task_id)
        task.stop_requested = True
        self._save_task(task)
        return task

    def assets(
        self,
        task_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        tagged_only: bool = True,
        tag: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        task = self.get_task(task_id)
        records = list(read_jsonl(task.workspace / "assets.jsonl"))
        latest = {record["asset_id"]: record for record in records}
        values = list(latest.values())
        if tagged_only:
            values = [record for record in values if record.get("tags")]
        if tag:
            values = [record for record in values if tag in record.get("tags", [])]
        if status:
            values = [record for record in values if record.get("review_status") == status]
        values.sort(key=lambda record: (record.get("directory", "").casefold(), record.get("group_key", "").casefold()))
        total = len(values)
        start = max(0, (page - 1) * page_size)
        return {"items": values[start : start + page_size], "total": total, "page": page, "page_size": page_size}

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

    def _move_record(self, task: TaskState, record: dict[str, Any]) -> dict[str, Any]:
        files = [Path(value) for value in record.get("files", [])]
        expected = record.get("snapshots", {})
        operation = {"asset_id": record["asset_id"], "started_at": _now(), "files": [], "status": "running"}
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
                ]
                if any(Path(name).suffix.casefold() in DEFAULT_VIDEO_EXTENSIONS for name in files):
                    groups.extend(discover_asset_groups(Path(root)))
            task.discovered = len(groups)
            self._save_task(task)
            completed_ids = set(self._latest_assets(task))
            pipeline = ScanPipeline(FFmpegTools(), self.ocr_engine, task.workspace / "evidence")
            for group in groups:
                asset_id = stable_asset_id(group)
                if asset_id in completed_ids:
                    task.completed += 1
                    continue
                if task.stop_requested:
                    task.status = "cancelled"
                    break
                task.current_file = str(group.directory / group.group_key)
                self._save_task(task)
                pipeline.scan_group(group)
                record = group_to_dict(group, asset_id=asset_id)
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
                )
                if task.status == "running":
                    task.status = "cancelled"
                self._tasks[task.task_id] = task
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue

