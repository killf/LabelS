import json
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from backend.adapter.persistence import crud_auto_label_job
from backend.application.service import auto_label
from backend.common.db import begin_transaction
from backend.common.storage import get_storage_backend
from backend.domain.models.auto_label_job import AutoLabelJob
from backend.domain.models.sample import TaskSample
from backend.tests.conftest import TestingSessionLocal


class Vector(list):
    def tolist(self) -> list:
        return list(self)


@pytest.fixture
def ai_task(client: TestClient, testuser_token_headers: dict) -> tuple[int, int]:
    headers = testuser_token_headers
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": "AI detection",
            "media_type": "IMAGE",
            "dataset_data_source_id": 1,
        },
    ).json()["data"]
    config = {
        "tools": [
            {
                "tool": "rectTool",
                "config": {"attributes": [{"key": "Object", "value": "object"}]},
            }
        ]
    }
    client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"config": json.dumps(config), "ai_model_name": "20261107-1.pt"},
    )
    content = BytesIO()
    Image.new("RGB", (100, 80), "blue").save(content, format="PNG")
    attachment = client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        headers=headers,
        files={"file": ("sample.png", content.getvalue(), "image/png")},
    ).json()["data"]
    sample_id = client.post(
        f"/api/v1/tasks/{task['id']}/samples",
        headers=headers,
        json=[{"file_id": attachment["id"], "data": {}}],
    ).json()["data"]["ids"][0]
    return task["id"], sample_id


def test_yolo_prediction_is_editable_and_does_not_complete_sample(
    client: TestClient,
    testuser_token_headers: dict,
    ai_task: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = SimpleNamespace(
        names={0: "Object", 1: "unconfigured"},
        boxes=SimpleNamespace(
            xyxy=Vector([[10, 20, 50, 40], [0, 0, 10, 10]]),
            cls=Vector([0, 1]),
            conf=Vector([0.9, 0.8]),
        ),
    )
    model = SimpleNamespace(predict=lambda *args, **kwargs: [prediction])

    @contextmanager
    def load_model(*args):
        yield model

    monkeypatch.setattr(auto_label, "_load_model", load_model)
    task_id, sample_id = ai_task
    for _ in range(2):
        response = client.post(
            f"/api/v1/tasks/{task_id}/samples/{sample_id}/auto_label",
            headers=testuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["data"]["warning_message"]

    annotations = client.get(
        f"/api/v1/tasks/{task_id}/pre_annotations",
        params={"sample_name": "sample.png", "page": 0},
        headers=testuser_token_headers,
    ).json()["data"]
    assert len(annotations) == 1
    payload = json.loads(annotations[0]["data"])
    boxes = payload["annotations"]["rectTool"]["result"]
    assert len(boxes) == 1 and boxes[0]["label"] == "object"
    assert (boxes[0]["x"], boxes[0]["width"]) == (10, 40)
    sample = client.get(
        f"/api/v1/tasks/{task_id}/samples/{sample_id}", headers=testuser_token_headers
    ).json()["data"]
    assert sample["state"] == "NEW" and sample["data"] == {}


def test_batch_reuses_model_and_reports_partial_failure(
    db: Session,
    ai_task: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, sample_id = ai_task
    first = db.get(TaskSample, sample_id)
    with begin_transaction(db):
        second = TaskSample(
            task_id=task_id,
            file_id=first.file_id,
            inner_id=2,
            created_by=first.created_by,
            updated_by=first.created_by,
            data="{}",
        )
        db.add(second)
        db.flush()
        second_id = second.id
        job = crud_auto_label_job.create(
            db, task_id, first.created_by, 2, "20261107-1.pt"
        )
        job_id = job.id
    loads = []

    @contextmanager
    def load_model(*args):
        loads.append(1)
        yield object()

    def predict(model, sample, task, model_name):
        if sample.id == second_id:
            raise RuntimeError("synthetic inference failure")
        return {
            "sample_name": "sample.png",
            "annotations": {},
            "meta": {"source_type": "ai_generated", "sample_id": sample.id},
        }

    monkeypatch.setattr(auto_label, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(auto_label, "_load_model", load_model)
    monkeypatch.setattr(auto_label, "_predict", predict)
    auto_label._run_batch(job_id, [sample_id, second_id])
    db.expire_all()
    completed = db.get(AutoLabelJob, job_id)
    assert loads == [1]
    assert (
        completed.status,
        completed.processed_count,
        completed.success_count,
        completed.failed_count,
    ) == ("FAILED", 2, 1, 1)
    assert completed.error_message


def test_restart_marks_unfinished_ai_job_as_interrupted(
    db: Session,
    ai_task: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, sample_id = ai_task
    sample = db.get(TaskSample, sample_id)
    with begin_transaction(db):
        job = crud_auto_label_job.create(
            db, task_id, sample.created_by, 1, "20261107-1.pt"
        )
        job_id = job.id
    monkeypatch.setattr(auto_label, "SessionLocal", TestingSessionLocal)
    auto_label.fail_interrupted_jobs()
    db.expire_all()
    assert db.get(AutoLabelJob, job_id).status == "FAILED"


def test_list_dataset_model_weights(
    client: TestClient, testuser_token_headers: dict, ai_task: tuple[int, int]
) -> None:
    task_id, _ = ai_task
    get_storage_backend().save_bytes(
        b"synthetic weight", "datasets/models/20261107-1.pt"
    )
    response = client.get(
        f"/api/v1/tasks/{task_id}/models", headers=testuser_token_headers
    )
    assert response.status_code == 200
    assert response.json()["data"] == ["20261107-1.pt"]


def test_missing_batch_job_does_not_load_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auto_label, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        auto_label,
        "_load_model",
        lambda *args: pytest.fail("missing job loaded a model"),
    )
    auto_label._run_batch(999999, [])


@pytest.mark.parametrize("name", ["../escape.pt", "..\\escape.pt", "C:\\escape.pt"])
def test_model_names_reject_paths_before_loading(name: str):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        with auto_label._load_model(None, None, name):
            pytest.fail("invalid model path reached inference")
    assert error.value.status_code == 422
