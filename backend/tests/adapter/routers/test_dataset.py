import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from PIL import Image

from backend.application.service import dataset
from backend.common.storage import get_storage


@pytest.fixture
def annotated_sample(
    client: TestClient, testuser_token_headers: dict
) -> tuple[int, int]:
    headers = testuser_token_headers
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": "YOLO dataset",
            "media_type": "IMAGE",
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
    response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"config": json.dumps(config)},
    )
    assert response.status_code == 200

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
    result = {
        "width": 100,
        "height": 80,
        "rotate": 0,
        "rectTool": {
            "result": [{"x": 10, "y": 20, "width": 40, "height": 20, "label": "object"}]
        },
    }
    response = client.patch(
        f"/api/v1/tasks/{task['id']}/samples/{sample_id}",
        headers=headers,
        json={
            "state": "DONE",
            "data": {"result": json.dumps(result)},
            "annotated_count": 1,
        },
    )
    assert response.status_code == 200
    return task["id"], sample_id


def _read(key: str) -> str:
    return get_storage().read_text(f"tasks/1/{key}")


def test_annotation_and_split_update_preserve_yolo_dataset(
    client: TestClient, testuser_token_headers: dict, annotated_sample: tuple[int, int]
) -> None:
    task_id, sample_id = annotated_sample
    path = f"/api/v1/tasks/{task_id}/samples/{sample_id}"
    original = client.get(path, headers=testuser_token_headers).json()["data"]
    assert _read(f"labels/{sample_id}.txt") == (
        "0 0.30000000 0.37500000 0.40000000 0.25000000\n"
    )
    config = yaml.safe_load(_read("data.yaml"))
    assert config["names"] == ["Object"]
    assert config["val"] == config["test"] == "test.txt"
    assert not get_storage().exists(f"tasks/{task_id}/val.txt")

    for split in ["test", "train"]:
        response = client.patch(
            path, headers=testuser_token_headers, json={"split": split}
        )
        assert response.status_code == 200
        assert response.json()["data"]["data"] == original["data"]
        for name in ["train", "test"]:
            expected = f"images/{sample_id}.png\n" if name == split else ""
            assert _read(f"{name}.txt").strip() == expected.strip()


def test_skipped_sample_is_removed_from_training_files(
    client: TestClient, testuser_token_headers: dict, annotated_sample: tuple[int, int]
) -> None:
    task_id, sample_id = annotated_sample
    response = client.patch(
        f"/api/v1/tasks/{task_id}/samples/{sample_id}",
        headers=testuser_token_headers,
        json={"state": "SKIPPED"},
    )
    assert response.status_code == 200
    assert _read("train.txt").strip() == ""
    assert not get_storage().exists(f"tasks/{task_id}/labels/{sample_id}.txt")


def test_sync_failure_keeps_annotation_and_can_be_retried(
    client: TestClient,
    testuser_token_headers: dict,
    annotated_sample: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, sample_id = annotated_sample
    path = f"/api/v1/tasks/{task_id}/samples/{sample_id}"
    failed_client = Mock()
    failed_client.save_bytes.side_effect = OSError("test disk failure")
    with monkeypatch.context() as patch:
        patch.setattr(dataset, "get_storage", lambda: failed_client)
        response = client.patch(
            path, headers=testuser_token_headers, json={"split": "test"}
        )
        assert response.status_code == 500
        saved = client.get(path, headers=testuser_token_headers).json()["data"]
        assert saved["split"] == "test" and saved["state"] == "DONE"

    response = client.patch(
        path, headers=testuser_token_headers, json={"split": "test"}
    )
    assert response.status_code == 200
    assert _read("test.txt") == f"images/{sample_id}.png\n"


def test_removed_export_routes_and_single_migration_head(client: TestClient) -> None:
    response = client.get("/openapi.json")
    schema = response.json()
    assert schema["info"]["title"] == "LabelS"
    assert response.headers["LabelS-Version"] == schema["info"]["version"]

    paths = schema["paths"]
    assert not any("/export" in path for path in paths)

    directory = Path(__file__).resolve().parents[3] / "migrations"
    config = Config()
    config.set_main_option("script_location", str(directory))
    heads = ScriptDirectory.from_config(config).get_heads()
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())
    assert len(revisions) == 1
    assert heads == [revisions[0].revision]
    assert revisions[0].down_revision is None


@pytest.mark.parametrize(
    "box",
    [
        {"x": 10, "y": 20, "width": 40, "height": 20, "label": "unknown"},
        {"x": 200, "y": 20, "width": 40, "height": 20, "label": "object"},
    ],
)
def test_invalid_annotation_keeps_existing_training_label(
    client: TestClient,
    testuser_token_headers: dict,
    annotated_sample: tuple[int, int],
    box: dict,
):
    task_id, sample_id = annotated_sample
    original = _read(f"labels/{sample_id}.txt")
    response = client.patch(
        f"/api/v1/tasks/{task_id}/samples/{sample_id}",
        headers=testuser_token_headers,
        json={
            "state": "DONE",
            "data": {"result": json.dumps({"rectTool": {"result": [box]}})},
        },
    )
    assert response.status_code == 422
    assert _read(f"labels/{sample_id}.txt") == original


def test_background_sample_has_an_empty_label_file(
    client: TestClient,
    testuser_token_headers: dict,
    annotated_sample: tuple[int, int],
):
    task_id, sample_id = annotated_sample
    response = client.patch(
        f"/api/v1/tasks/{task_id}/samples/{sample_id}",
        headers=testuser_token_headers,
        json={
            "state": "DONE",
            "data": {"result": json.dumps({"rectTool": {"result": []}})},
            "annotated_count": 0,
        },
    )
    assert response.status_code == 200
    assert _read(f"labels/{sample_id}.txt") == ""
    assert _read("train.txt") == f"images/{sample_id}.png\n"
