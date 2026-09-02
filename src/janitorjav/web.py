from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from .models import ReviewStatus
from .task_manager import TaskManager


class CreateTaskRequest(BaseModel):
    scan_root: str
    video_workers: int = Field(default=1, ge=1, le=8)


class AssetActionRequest(BaseModel):
    asset_ids: list[str]


class ReviewActionRequest(AssetActionRequest):
    status: ReviewStatus


class DirectoryActionRequest(BaseModel):
    directory: str


def create_app(manager: TaskManager) -> FastAPI:
    app = FastAPI(title="JanitorJAV", version="0.1.0")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {"tasks": manager.list_tasks()})

    @app.get("/tasks/{task_id}")
    def task_page(request: Request, task_id: str):
        try:
            task = manager.get_task(task_id)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        return templates.TemplateResponse(request, "task.html", {"task": task.to_dict()})

    @app.get("/api/tasks")
    def list_tasks() -> list[dict[str, Any]]:
        return manager.list_tasks()

    @app.post("/api/tasks")
    def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
        try:
            return manager.create_task(
                Path(payload.scan_root), video_workers=payload.video_workers
            ).to_dict()
        except (OSError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/tasks/{task_id}")
    def task_status(task_id: str) -> dict[str, Any]:
        try:
            return manager.get_task(task_id).to_dict()
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/tasks/{task_id}/start")
    def start_task(task_id: str) -> dict[str, Any]:
        try:
            return manager.start_task(task_id).to_dict()
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        try:
            return manager.cancel_task(task_id).to_dict()
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, bool]:
        try:
            manager.delete_task(task_id)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/pause")
    def pause_task(task_id: str) -> dict[str, Any]:
        try:
            return manager.pause_task(task_id).to_dict()
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/tasks/{task_id}/assets")
    def list_assets(
        task_id: str,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 50,
        tagged_only: bool = True,
        tag: str | None = None,
        status: str | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        ocr_keyword: str | None = None,
    ) -> dict[str, Any]:
        try:
            return manager.assets(
                task_id,
                page=page,
                page_size=page_size,
                tagged_only=tagged_only,
                tag=tag,
                status=status,
                min_duration=min_duration,
                max_duration=max_duration,
                min_width=min_width,
                min_height=min_height,
                ocr_keyword=ocr_keyword,
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/tasks/{task_id}/review")
    def review_assets(task_id: str, payload: ReviewActionRequest) -> dict[str, bool]:
        try:
            manager.set_review_status(task_id, payload.asset_ids, payload.status)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/matching-asset-ids")
    def matching_asset_ids(
        task_id: str,
        min_score: Annotated[int | None, Query(ge=0)] = None,
        tagged_only: bool = True,
        tag: str | None = None,
        status: str | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        min_width: int | None = None,
        min_height: int | None = None,
        ocr_keyword: str | None = None,
    ) -> dict[str, Any]:
        try:
            ids = manager.matching_asset_ids(
                task_id,
                min_score=min_score,
                tagged_only=tagged_only,
                tag=tag,
                status=status,
                min_duration=min_duration,
                max_duration=max_duration,
                min_width=min_width,
                min_height=min_height,
                ocr_keyword=ocr_keyword,
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        return {"asset_ids": ids, "total": len(ids)}

    @app.post("/api/tasks/{task_id}/quarantine")
    def quarantine_assets(task_id: str, payload: AssetActionRequest) -> dict[str, Any]:
        try:
            return {"operations": manager.quarantine_assets(task_id, payload.asset_ids)}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/tasks/{task_id}/quarantine-ready")
    def quarantine_ready_assets(task_id: str) -> dict[str, Any]:
        try:
            return {"operations": manager.quarantine_ready_assets(task_id)}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/tasks/{task_id}/restore")
    def restore_assets(task_id: str, payload: AssetActionRequest) -> dict[str, Any]:
        try:
            return {"operations": manager.restore_assets(task_id, payload.asset_ids)}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/tasks/{task_id}/quarantine-directory")
    def quarantine_directory(task_id: str, payload: DirectoryActionRequest) -> dict[str, Any]:
        try:
            return manager.quarantine_directory(task_id, Path(payload.directory))
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/tasks/{task_id}/restore-directory")
    def restore_directory(task_id: str, payload: DirectoryActionRequest) -> dict[str, Any]:
        try:
            return manager.restore_directory(task_id, Path(payload.directory))
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/tasks/{task_id}/evidence")
    def evidence(task_id: str, path: str) -> FileResponse:
        task = manager.get_task(task_id)
        requested = Path(path).resolve()
        evidence_root = (task.workspace / "evidence").resolve()
        try:
            requested.relative_to(evidence_root)
        except ValueError as error:
            raise HTTPException(403, "Evidence path is outside this task") from error
        if not requested.is_file():
            raise HTTPException(404, "Evidence file not found")
        return FileResponse(requested)

    @app.post("/api/tasks/{task_id}/open-directory")
    def open_directory(task_id: str, path: str) -> dict[str, bool]:
        task = manager.get_task(task_id)
        requested = Path(path).resolve()
        roots = (task.scan_root.resolve(), task.quarantine_root.resolve())
        if not any(_is_inside(requested, root) for root in roots):
            raise HTTPException(403, "Directory is outside task roots")
        if not requested.is_dir():
            raise HTTPException(404, "Directory not found")
        try:
            subprocess.Popen(["explorer.exe", str(requested)])
        except OSError as error:
            raise HTTPException(500, str(error)) from error
        return {"ok": True}

    return app


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
