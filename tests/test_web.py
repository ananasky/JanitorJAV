import time
from pathlib import Path

from fastapi.testclient import TestClient

from janitorjav.ocr import OCRLine
from janitorjav.task_manager import TaskManager
from janitorjav.web import create_app


class EmptyOCR:
    name = "empty"

    def recognize(self, image_paths: list[Path]) -> list[list[OCRLine]]:
        return [[] for _ in image_paths]


def test_create_and_complete_empty_task(tmp_path: Path) -> None:
    scan_root = tmp_path / "JAV"
    scan_root.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    client = TestClient(create_app(manager))

    response = client.post("/api/tasks", json={"scan_root": str(scan_root), "video_workers": 7})
    assert response.status_code == 200
    assert response.json()["video_workers"] == 7
    task_id = response.json()["task_id"]
    assert (tmp_path / "JanitorJAV_Quarantine").is_dir()

    response = client.post(f"/api/tasks/{task_id}/start")
    assert response.status_code == 200
    for _ in range(100):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] == "completed":
            break
        time.sleep(0.01)
    assert task["status"] == "completed"
    assert task["discovered"] == 0


def test_pages_render(tmp_path: Path) -> None:
    scan_root = tmp_path / "JAV"
    scan_root.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    client = TestClient(create_app(manager))
    task = manager.create_task(scan_root)

    assert client.get("/").status_code == 200
    response = client.get(f"/tasks/{task.task_id}")
    assert response.status_code == 200
    assert task.task_id in response.text
    assert 'id="task-controls"' in response.text
    assert 'id="selection-toggle"' in response.text
    assert 'a.flagged' in response.text
    assert 'id="page-jump"' in response.text
    assert '>跳转</button>' in response.text
    assert '执行全部待隔离' in response.text
    assert 'reviewOne' in response.text
    assert 'data-list-status="pending"' in response.text
    assert 'data-list-status="keep"' in response.text
    assert 'data-list-status="ready_to_quarantine"' in response.text
    assert '不会自动补充记录' in response.text
    assert 'removeReviewed' in response.text
    assert 'class="toolbar review-toolbar"' in response.text
    assert '.review-toolbar { position:sticky' in response.text
    assert 'id="quarantine-selected"' in response.text
    assert 'updateActionControls' in response.text
    assert '所选记录尚未标记为待隔离' in response.text
    assert '识别汇总：' in response.text
    assert 's.related_text||[]' in response.text
    assert 'frame_count} 帧' not in response.text
    assert 'id="score-threshold"' in response.text
    assert '跨页全选分数≥' in response.text
    assert 'matching-asset-ids' in response.text


def test_rejects_non_empty_quarantine(tmp_path: Path) -> None:
    scan_root = tmp_path / "JAV"
    scan_root.mkdir()
    quarantine = tmp_path / "JanitorJAV_Quarantine"
    quarantine.mkdir()
    (quarantine / "existing.txt").touch()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    client = TestClient(create_app(manager))

    response = client.post("/api/tasks", json={"scan_root": str(scan_root)})
    assert response.status_code == 400
    assert "must be empty" in response.json()["detail"]


def test_rejects_video_workers_outside_supported_range(tmp_path: Path) -> None:
    scan_root = tmp_path / "JAV"
    scan_root.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    client = TestClient(create_app(manager))

    response = client.post(
        "/api/tasks", json={"scan_root": str(scan_root), "video_workers": 9}
    )

    assert response.status_code == 422


def test_delete_completed_task_removes_workspace(tmp_path: Path) -> None:
    scan_root = tmp_path / "JAV"
    scan_root.mkdir()
    manager = TaskManager(EmptyOCR(), workspace_root=tmp_path / "tasks")
    client = TestClient(create_app(manager))
    task = manager.create_task(scan_root)
    workspace = task.workspace

    response = client.delete(f"/api/tasks/{task.task_id}")

    assert response.status_code == 200
    assert not workspace.exists()
    assert client.get("/api/tasks").json() == []
