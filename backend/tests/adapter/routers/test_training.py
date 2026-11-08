import asyncio
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from backend.application.service import training
from backend.common.db import begin_transaction
from backend.common.storage import get_storage
from backend.domain.models.project import Project
from backend.domain.models.training_run import TrainingRun
from backend.tests.conftest import TestingSessionLocal


@pytest.fixture
def training_project(client, testuser_token_headers):
    """通过公共接口准备分别含一张人工完成图片的训练集和测试集。"""
    headers = testuser_token_headers
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "Page training",
            "media_type": "IMAGE",
        },
    ).json()["data"]
    project_id = project["id"]
    config = {
        "tools": [
            {
                "tool": "rectTool",
                "config": {"attributes": [{"key": "person", "value": "person"}]},
            }
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers,
        json={"config": json.dumps(config)},
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
            f"/api/v1/projects/{project_id}/attachments",
            headers=headers,
            files={"file": (f"{split}.png", content.getvalue(), "image/png")},
        ).json()["data"]
        sample_id = client.post(
            f"/api/v1/projects/{project_id}/samples",
            headers=headers,
            json=[{"file_id": attachment["id"], "split": split}],
        ).json()["data"]["ids"][0]
        response = client.patch(
            f"/api/v1/projects/{project_id}/samples/{sample_id}",
            headers=headers,
            json={
                "state": "DONE",
                "data": {"result": json.dumps(result)},
                "annotated_count": 1,
            },
        )
        assert response.status_code == 200
    return project_id


def test_project_initializes_fixed_directories(client, testuser_token_headers):
    response = client.post(
        "/api/v1/projects",
        headers=testuser_token_headers,
        json={"name": "Automatic directory", "media_type": "IMAGE"},
    )
    assert response.status_code == 201
    project = response.json()["data"]
    assert project["dataset_prefix"] == f"projects/{project['id']}"
    assert "dataset_data_source_id" not in project
    storage = get_storage()
    for directory in ["", "uploads/", "images/", "labels/", "models/", "runs/"]:
        assert storage.path(f"projects/{project['id']}/{directory}").is_dir()
    client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=testuser_token_headers,
        json={"name": "Renamed"},
    )
    assert (
        client.get(
            f"/api/v1/projects/{project['id']}", headers=testuser_token_headers
        ).json()["data"]["dataset_prefix"]
        == project["dataset_prefix"]
    )


def test_failed_directory_creation_rolls_back_project(
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
        "/api/v1/projects",
        headers=testuser_token_headers,
        json={"name": "Must not remain", "media_type": "IMAGE"},
    )
    assert response.status_code == 500
    db.expire_all()
    assert db.query(Project).filter(Project.name == "Must not remain").count() == 0
    assert not storage.path("projects/1/").exists()


def test_removed_import_routes_and_val_split(
    client, testuser_token_headers, training_project
):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(
        "datasources" in path or "import_s3" in path or "pre_annotations/files" in path
        for path in paths
    )
    assert "post" not in paths["/api/v1/projects/{project_id}/pre_annotations"]
    response = client.patch(
        f"/api/v1/projects/{training_project}/samples/1",
        headers=testuser_token_headers,
        json={"split": "val"},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/projects/{training_project}/attachments",
        headers=testuser_token_headers,
        files={"file": ("annotations.json", b"{}", "application/json")},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/projects/{training_project}/attachments",
        headers=testuser_token_headers,
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422


def test_training_queue_and_duplicate_start(
    client, testuser_token_headers, training_project, monkeypatch
):
    async def pending(_run_id):
        return

    monkeypatch.setattr(training, "_run", pending)
    monkeypatch.setattr(training.importlib.util, "find_spec", lambda _name: object())
    url = f"/api/v1/projects/{training_project}/training-runs"
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
        {"algorithm": "yolo11_detect"},
        {"extra_params": []},
        {"extra_params": None},
        {"extra_params": {"epochs": 2}},
        {"extra_params": {"data": "outside"}},
        {"extra_params": {"save": False}},
    ],
)
def test_training_rejects_invalid_parameters(
    client, testuser_token_headers, training_project, body
):
    response = client.post(
        f"/api/v1/projects/{training_project}/training-runs",
        headers=testuser_token_headers,
        json=body,
    )
    assert response.status_code == 422


def test_training_records_require_project_access(
    client, testuser_token_headers, training_project, db
):
    from backend.domain.models.user import User

    with begin_transaction(db):
        user = User(username="other-training@example.com", hashed_password="test-only")
        db.add(user)
        db.flush()
        db.get(Project, training_project).created_by = user.id
    for tail in ["", "/1", "/1/log"]:
        assert (
            client.get(
                f"/api/v1/projects/{training_project}/training-runs{tail}",
                headers=testuser_token_headers,
            ).status_code
            == 403
        )


@pytest.mark.parametrize("exit_code,expected", [(0, "SUCCEEDED"), (1, "FAILED")])
@pytest.mark.parametrize("extra_params", [{}, {"lr0": 0.001, "amp": False}])
def test_worker_records_process_result(
    training_project, db, monkeypatch, tmp_path, exit_code, expected, extra_params
):
    with begin_transaction(db):
        project = db.get(Project, training_project)
        run = TrainingRun(
            project_id=training_project,
            created_by=project.created_by,
            initial_model="yolo26n.pt",
            parameters=json.dumps(
                {
                    "epochs": 2,
                    "imgsz": 640,
                    "batch": 2,
                    **({"extra_params": extra_params} if extra_params else {}),
                }
            ),
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
            f"projects/{training_project}"
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
    if extra_params:
        arguments = captured["args"]
        assert (
            json.loads(arguments[arguments.index("--extra-params") + 1]) == extra_params
        )
    else:
        assert "--extra-params" not in captured["args"]
    if exit_code == 0:
        assert saved.model_name == "20261107-1.pt"
        assert json.loads(saved.metrics)["metrics/mAP50(B)"] == 0.5
    else:
        assert saved.model_name is None and "1" in saved.error_message


def test_custom_training_parameters_are_saved_and_returned(
    client, testuser_token_headers, training_project, monkeypatch
):
    async def pending(_run_id):
        return

    monkeypatch.setattr(training, "_run", pending)
    monkeypatch.setattr(training.importlib.util, "find_spec", lambda _name: object())
    validate = Mock()
    monkeypatch.setattr(training, "validate_training_options", validate)
    parameters = {"lr0": 0.001, "amp": False, "seed": 7}
    url = f"/api/v1/projects/{training_project}/training-runs"
    response = client.post(
        url, headers=testuser_token_headers, json={"extra_params": parameters}
    )
    assert response.status_code == 202
    record = response.json()["data"]
    assert record["parameters"]["extra_params"] == parameters
    validate.assert_called_once_with(parameters)
    detail = client.get(f"{url}/{record['id']}", headers=testuser_token_headers)
    assert detail.json()["data"]["parameters"]["extra_params"] == parameters


def test_invalid_framework_options_do_not_create_a_run(
    client, testuser_token_headers, training_project, monkeypatch, db
):
    monkeypatch.setattr(training.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        training,
        "validate_training_options",
        Mock(side_effect=ValueError("未知训练参数：typo")),
    )
    response = client.post(
        f"/api/v1/projects/{training_project}/training-runs",
        headers=testuser_token_headers,
        json={"extra_params": {"typo": 1}},
    )
    assert response.status_code == 422
    db.expire_all()
    assert db.query(TrainingRun).count() == 0


def test_parameter_catalog_requires_project_access(
    client, testuser_token_headers, training_project, monkeypatch, db
):
    from backend.domain.models.user import User

    catalog = Mock(
        return_value=[{"name": "lr0", "default": 0.01, "description": "初始学习率"}]
    )
    monkeypatch.setattr(training, "training_parameter_catalog", catalog)
    url = f"/api/v1/projects/{training_project}/training-runs/parameters"
    response = client.get(url, headers=testuser_token_headers)
    assert response.status_code == 200
    assert response.json()["data"][0]["name"] == "lr0"
    catalog.assert_called_once_with()
    assert client.get(url).status_code == 401
    with begin_transaction(db):
        user = User(username="catalog-other@example.com", hashed_password="test-only")
        db.add(user)
        db.flush()
        db.get(Project, training_project).created_by = user.id
    assert client.get(url, headers=testuser_token_headers).status_code == 403
    assert catalog.call_count == 1


def test_parameter_catalog_handles_unavailable_runtime(
    client, testuser_token_headers, training_project, monkeypatch
):
    monkeypatch.setattr(
        training, "training_parameter_catalog", Mock(side_effect=ImportError)
    )
    response = client.get(
        f"/api/v1/projects/{training_project}/training-runs/parameters",
        headers=testuser_token_headers,
    )
    assert response.status_code == 503
