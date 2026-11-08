import json
from datetime import datetime

import pytest

from backend.common.db import begin_transaction
from backend.common.storage import get_storage
from backend.domain.models.task import Task
from backend.domain.models.training_run import TrainingRun
from backend.tests.adapter.routers.test_training import training_task


@pytest.fixture
def completed_run(training_task, db):
    """创建可丢弃的终态记录、模型和日志，验证三个对象的清理边界。"""
    with begin_transaction(db):
        task = db.get(Task, training_task)
        run = TrainingRun(
            task_id=training_task,
            created_by=task.created_by,
            initial_model="yolo26n.pt",
            parameters=json.dumps({"epochs": 2, "imgsz": 640, "batch": 2}),
            status="SUCCEEDED",
            model_name="test-cleanup.pt",
            created_at=datetime.now(),
        )
        db.add(run)
        db.flush()
        run_id = run.id
    storage = get_storage()
    storage.save_bytes(
        b"test-only model", f"tasks/{training_task}/models/test-cleanup.pt"
    )
    storage.save_bytes(
        b"test-only log", f"tasks/{training_task}/runs/{run_id}/console.log"
    )
    storage.save_bytes(
        b"intermediate", f"tasks/{training_task}/runs/{run_id}/training/last.pt"
    )
    return training_task, run_id


def test_authenticated_model_download(client, testuser_token_headers, completed_run):
    task_id, _ = completed_run
    url = f"/api/v1/tasks/{task_id}/models/test-cleanup.pt"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=testuser_token_headers)
    assert response.status_code == 200 and response.content == b"test-only model"
    assert "attachment" in response.headers["content-disposition"]
    assert "test-cleanup.pt" in response.headers["content-disposition"]
    assert (
        client.get(
            f"/api/v1/tasks/{task_id}/models/absent.pt", headers=testuser_token_headers
        ).status_code
        == 404
    )


def test_clear_logs_preserves_record_and_model(
    client, testuser_token_headers, completed_run, db
):
    task_id, run_id = completed_run
    path = f"/api/v1/tasks/{task_id}/training-runs/{run_id}"
    assert (
        client.request(
            "DELETE", f"{path}/log", headers=testuser_token_headers
        ).status_code
        == 200
    )
    db.expire_all()
    assert db.get(TrainingRun, run_id) is not None
    assert get_storage().exists(f"tasks/{task_id}/models/test-cleanup.pt")
    assert not get_storage().path(f"tasks/{task_id}/runs/{run_id}").exists()
    record = client.get(path, headers=testuser_token_headers).json()["data"]
    assert record["model_available"] and not record["log_available"]


def test_log_response_removes_terminal_control_codes(
    client, testuser_token_headers, completed_run
):
    task_id, run_id = completed_run
    raw = b"\x1b[32mepoch 1\x1b[0m\repoch 2\n"
    path = f"tasks/{task_id}/runs/{run_id}/console.log"
    get_storage().save_bytes(raw, path)
    response = client.get(
        f"/api/v1/tasks/{task_id}/training-runs/{run_id}/log",
        headers=testuser_token_headers,
    )
    assert response.status_code == 200
    assert response.text == "epoch 1\nepoch 2\n"
    assert get_storage().read_bytes(path) == raw


def test_clear_record_includes_model_and_logs(
    client, testuser_token_headers, completed_run, db
):
    task_id, run_id = completed_run
    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{task_id}/training-runs/{run_id}",
        headers=testuser_token_headers,
    )
    assert response.status_code == 200
    db.expire_all()
    assert db.get(TrainingRun, run_id) is None
    assert not get_storage().exists(f"tasks/{task_id}/models/test-cleanup.pt")
    assert not get_storage().path(f"tasks/{task_id}/runs/{run_id}").exists()


def test_model_in_use_blocks_record_cleanup(
    client, testuser_token_headers, completed_run, db
):
    task_id, run_id = completed_run
    client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=testuser_token_headers,
        json={"ai_model_name": "test-cleanup.pt"},
    )
    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{task_id}/training-runs/{run_id}",
        headers=testuser_token_headers,
    )
    assert response.status_code == 409
    db.expire_all()
    assert db.get(TrainingRun, run_id) is not None
    assert get_storage().exists(f"tasks/{task_id}/models/test-cleanup.pt")


def test_running_record_cannot_be_cleaned(
    client, testuser_token_headers, completed_run, db
):
    task_id, run_id = completed_run
    with begin_transaction(db):
        db.get(TrainingRun, run_id).status = "RUNNING"
    for tail in ["", "/log"]:
        response = client.request(
            "DELETE",
            f"/api/v1/tasks/{task_id}/training-runs/{run_id}{tail}",
            headers=testuser_token_headers,
        )
        assert response.status_code == 409
    assert get_storage().exists(f"tasks/{task_id}/models/test-cleanup.pt")


def test_cleanup_failure_retains_record(
    client, testuser_token_headers, completed_run, db, monkeypatch
):
    from backend.application.service import training

    task_id, run_id = completed_run

    def fail(_path):
        raise OSError("test file permission failure")

    monkeypatch.setattr(training, "_remove_logs", lambda *_: fail(None))
    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{task_id}/training-runs/{run_id}",
        headers=testuser_token_headers,
    )
    assert response.status_code == 500
    db.expire_all()
    assert db.get(TrainingRun, run_id) is not None
    assert get_storage().exists(f"tasks/{task_id}/models/test-cleanup.pt")
