import asyncio
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from backend.application.service import training
from backend.common.config import settings
from backend.common.db import begin_transaction
from backend.common.storage import get_storage
from backend.domain.models.task import Task
from backend.domain.models.training_run import TrainingRun
from backend.tests.conftest import TestingSessionLocal


@pytest.fixture
def training_task(client, testuser_token_headers):
    """通过公共接口准备分别含一张人工完成图片的训练集和测试集。"""
    headers = testuser_token_headers
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": "Page training",
            "media_type": "IMAGE",
        },
    ).json()["data"]
    task_id = task["id"]
    config = {
        "tools": [
            {
                "tool": "rectTool",
                "config": {"attributes": [{"key": "person", "value": "person"}]},
            }
        ]
    }
    response = client.patch(
        f"/api/v1/tasks/{task_id}", headers=headers, json={"config": json.dumps(config)}
    )
    assert response.status_code == 200
    content = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(content, format="PNG")
    result = {
        "width": 10,
        "height": 10,
        "rectTool": {
            "result": [{"x": 1, "y": 1, "width": 3, "height": 4, "label": "person"}]
        },
    }
    for split in ["train", "test"]:
        attachment = client.post(
            f"/api/v1/tasks/{task_id}/attachments",
            headers=headers,
            files={"file": (f"{split}.png", content.getvalue(), "image/png")},
        ).json()["data"]
        sample_id = client.post(
            f"/api/v1/tasks/{task_id}/samples",
            headers=headers,
            json=[{"file_id": attachment["id"], "split": split}],
        ).json()["data"]["ids"][0]
        response = client.patch(
            f"/api/v1/tasks/{task_id}/samples/{sample_id}",
            headers=headers,
            json={
                "state": "DONE",
                "data": {"result": json.dumps(result)},
                "annotated_count": 1,
            },
        )
        assert response.status_code == 200
    return task_id


def test_task_initializes_fixed_directories(client, testuser_token_headers):
    response = client.post(
        "/api/v1/tasks",
        headers=testuser_token_headers,
        json={"name": "Automatic directory", "media_type": "IMAGE"},
    )
    assert response.status_code == 201
    task = response.json()["data"]
    assert task["dataset_prefix"] == f"tasks/{task['id']}"
    assert "dataset_data_source_id" not in task
    storage = get_storage()
    for directory in ["", "uploads/", "images/", "labels/", "models/", "runs/"]:
        assert storage.path(f"tasks/{task['id']}/{directory}").is_dir()
    client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=testuser_token_headers,
        json={"name": "Renamed"},
    )
    assert (
        client.get(
            f"/api/v1/tasks/{task['id']}", headers=testuser_token_headers
        ).json()["data"]["dataset_prefix"]
        == task["dataset_prefix"]
    )


def test_failed_directory_creation_rolls_back_task(
    client, testuser_token_headers, db, monkeypatch
):
    storage = get_storage()
    original_mkdir = Path.mkdir

    def fail_images(path, *args, **kwargs):
        if path.name == "images":
            raise OSError("test disk failure")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_images)
    response = client.post(
        "/api/v1/tasks",
        headers=testuser_token_headers,
        json={"name": "Must not remain", "media_type": "IMAGE"},
    )
    assert response.status_code == 500
    db.expire_all()
    assert db.query(Task).filter(Task.name == "Must not remain").count() == 0
    assert not storage.path("tasks/1/").exists()


def test_removed_import_routes_and_val_split(
    client, testuser_token_headers, training_task
):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(
        "datasources" in path or "import_s3" in path or "pre_annotations/files" in path
        for path in paths
    )
    assert "post" not in paths[f"/api/v1/tasks/{{task_id}}/pre_annotations"]
    response = client.patch(
        f"/api/v1/tasks/{training_task}/samples/1",
        headers=testuser_token_headers,
        json={"split": "val"},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/tasks/{training_task}/attachments",
        headers=testuser_token_headers,
        files={"file": ("annotations.json", b"{}", "application/json")},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/tasks/{training_task}/attachments",
        headers=testuser_token_headers,
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422


def test_training_queue_and_duplicate_start(
    client, testuser_token_headers, training_task, monkeypatch
):
    async def pending(_run_id):
        return

    monkeypatch.setattr(training, "_run", pending)
    monkeypatch.setattr(training.importlib.util, "find_spec", lambda _name: object())
    url = f"/api/v1/tasks/{training_task}/training-runs"
    response = client.post(
        url,
        headers=testuser_token_headers,
        json={"initial_model": "yolo26n.pt", "epochs": 2, "imgsz": 640, "batch": 2},
    )
    assert response.status_code == 202
    run = response.json()["data"]
    assert run["status"] == "PENDING" and run["parameters"]["epochs"] == 2
    assert client.post(url, headers=testuser_token_headers, json={}).status_code == 409
    listing = client.get(url, headers=testuser_token_headers).json()
    assert listing["meta_data"]["total"] == 1
    assert (
        client.get(f"{url}/{run['id']}/log", headers=testuser_token_headers).text == ""
    )


@pytest.mark.parametrize(
    "body",
    [
        {"initial_model": "../outside.pt"},
        {"initial_model": "https://example.com/model.pt"},
        {"batch": 0},
        {"epochs": 0},
        {"imgsz": 641},
        {"command": "not allowed"},
    ],
)
def test_training_rejects_invalid_parameters(
    client, testuser_token_headers, training_task, body
):
    response = client.post(
        f"/api/v1/tasks/{training_task}/training-runs",
        headers=testuser_token_headers,
        json=body,
    )
    assert response.status_code == 422


def test_training_records_require_task_access(
    client, testuser_token_headers, training_task, db
):
    from backend.domain.models.user import User

    with begin_transaction(db):
        user = User(username="other-training@example.com", hashed_password="test-only")
        db.add(user)
        db.flush()
        db.get(Task, training_task).created_by = user.id
    for tail in ["", "/1", "/1/log"]:
        assert (
            client.get(
                f"/api/v1/tasks/{training_task}/training-runs{tail}",
                headers=testuser_token_headers,
            ).status_code
            == 403
        )


@pytest.mark.parametrize("exit_code,expected", [(0, "SUCCEEDED"), (1, "FAILED")])
def test_worker_records_process_result(
    training_task, db, monkeypatch, tmp_path, exit_code, expected
):
    with begin_transaction(db):
        task = db.get(Task, training_task)
        run = TrainingRun(
            task_id=training_task,
            created_by=task.created_by,
            initial_model="yolo26n.pt",
            parameters=json.dumps({"epochs": 2, "imgsz": 640, "batch": 2}),
            status="PENDING",
        )
        db.add(run)
        db.flush()
        run_id = run.id
    captured = {}

    class Process:
        returncode = exit_code

        async def wait(self):
            return exit_code

    async def spawn(*args, **kwargs):
        captured["args"] = args
        assert "shell" not in kwargs
        assert Path(args[args.index("--data") + 1]) == get_storage().path(
            f"tasks/{training_task}"
        )
        result = Path(args[args.index("--result-file") + 1])
        if exit_code == 0:
            result.write_text(
                json.dumps(
                    {
                        "run_id": "20261107-1",
                        "model_name": "20261107-1.pt",
                        "metrics": {"metrics/mAP50(B)": 0.5},
                    }
                )
            )
        return Process()

    monkeypatch.setattr(training, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(training, "_workspace", lambda *_: tmp_path)
    monkeypatch.setattr(training.asyncio, "create_subprocess_exec", spawn)
    asyncio.run(training._run(run_id))
    db.expire_all()
    saved = db.get(TrainingRun, run_id)
    assert saved.status == expected and saved.finished_at is not None
    assert "--workers" in captured["args"]
    if exit_code == 0:
        assert saved.model_name == "20261107-1.pt"
        assert json.loads(saved.metrics)["metrics/mAP50(B)"] == 0.5
    else:
        assert saved.model_name is None and "1" in saved.error_message
