import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from PIL import Image

from labelu.internal.application.service import dataset
from labelu.internal.common.storage import get_storage_backend


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
            "dataset_data_source_id": 1,
            "dataset_prefix": "ego-quality",
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
    return get_storage_backend().read_text(f"datasets/ego-quality/{key}")


def test_annotation_and_split_update_preserve_yolo_dataset(
    client: TestClient, testuser_token_headers: dict, annotated_sample: tuple[int, int]
) -> None:
    task_id, sample_id = annotated_sample
    path = f"/api/v1/tasks/{task_id}/samples/{sample_id}"
    original = client.get(path, headers=testuser_token_headers).json()["data"]
    assert _read(f"labels/{sample_id}.txt") == (
        "0 0.30000000 0.37500000 0.40000000 0.25000000\n"
    )
    assert yaml.safe_load(_read("data.yaml"))["names"] == ["Object"]

    for split in ["test", "val", "train"]:
        response = client.patch(
            path, headers=testuser_token_headers, json={"split": split}
        )
        assert response.status_code == 200
        assert response.json()["data"]["data"] == original["data"]
        for name in ["train", "test", "val"]:
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
    assert not get_storage_backend().exists(
        f"datasets/ego-quality/labels/{sample_id}.txt"
    )


def test_sync_failure_keeps_annotation_and_can_be_retried(
    client: TestClient,
    testuser_token_headers: dict,
    annotated_sample: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, sample_id = annotated_sample
    path = f"/api/v1/tasks/{task_id}/samples/{sample_id}"
    failed_client = Mock()
    failed_client.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
    )
    with monkeypatch.context() as patch:
        patch.setattr(dataset, "_build_s3_client", lambda source: failed_client)
        response = client.patch(
            path, headers=testuser_token_headers, json={"split": "test"}
        )
        assert response.status_code == 502
        saved = client.get(path, headers=testuser_token_headers).json()["data"]
        assert saved["split"] == "test" and saved["state"] == "DONE"

    response = client.patch(
        path, headers=testuser_token_headers, json={"split": "test"}
    )
    assert response.status_code == 200
    assert _read("test.txt") == f"images/{sample_id}.png\n"


def test_removed_export_routes_and_single_migration_head(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("/export" in path for path in paths)

    directory = Path(__file__).resolve().parents[4] / "labelu/alembic_labelu"
    config = Config()
    config.set_main_option("script_location", str(directory))
    heads = ScriptDirectory.from_config(config).get_heads()
    expected = (directory / "head.txt").read_text().strip().split("_", 1)[0]
    assert heads == [expected]
