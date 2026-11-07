from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.adapter.persistence import crud_attachment
from backend.common.config import settings
from backend.common.db import begin_transaction
from backend.domain.models.user import User

from fastapi.testclient import TestClient
from PIL import Image

from backend.common.storage import get_storage_backend


def test_upload_preview_and_delete_s3_attachment(
    client: TestClient, testuser_token_headers: dict
) -> None:
    headers = testuser_token_headers
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": "S3 upload",
            "media_type": "IMAGE",
            "dataset_data_source_id": 1,
        },
    ).json()["data"]
    content = BytesIO()
    Image.new("RGB", (100, 80), "blue").save(content, format="PNG")

    response = client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        headers=headers,
        files={"file": ("sample.png", content.getvalue(), "image/png")},
    )
    assert response.status_code == 201
    attachment = response.json()["data"]
    key = f"upload/{task['id']}/sample.png"
    storage = get_storage_backend()
    assert storage.read_bytes(key) == content.getvalue()
    assert storage.exists(f"upload/{task['id']}/sample-thumbnail.png")
    assert attachment["storage_backend"] == "s3"

    redirect = client.get(f"/api/v1/tasks/partial/{key}", follow_redirects=False)
    assert redirect.status_code == 404

    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{task['id']}/attachments",
        headers=headers,
        json={"attachment_ids": [attachment["id"]]},
    )
    assert response.status_code == 200
    assert not storage.exists(key)
    assert not storage.exists(f"upload/{task['id']}/sample-thumbnail.png")


def _create_task(client: TestClient, headers: dict) -> int:
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "name": "Upload boundary",
            "media_type": "IMAGE",
            "dataset_data_source_id": 1,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_upload_rejects_task_without_access(
    client: TestClient,
    testuser_token_headers: dict,
    db: Session,
):
    task_id = _create_task(client, testuser_token_headers)
    from backend.domain.models.task import Task

    with begin_transaction(db):
        other = User(username="other-upload@example.com", hashed_password="test-only")
        db.add(other)
        db.flush()
        db.get(Task, task_id).created_by = other.id
    response = client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        headers=testuser_token_headers,
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    assert response.status_code == 403
    assert not get_storage_backend().exists(f"upload/{task_id}/private.txt")


def test_delete_rejects_attachment_from_another_task(
    client: TestClient,
    testuser_token_headers: dict,
):
    first = _create_task(client, testuser_token_headers)
    second = _create_task(client, testuser_token_headers)
    response = client.post(
        f"/api/v1/tasks/{second}/attachments",
        headers=testuser_token_headers,
        files={"file": ("keep.txt", b"keep", "text/plain")},
    )
    assert response.status_code == 201
    attachment_id = response.json()["data"]["id"]
    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{first}/attachments",
        headers=testuser_token_headers,
        json={"attachment_ids": [attachment_id]},
    )
    assert response.status_code == 403
    assert get_storage_backend().read_bytes(f"upload/{second}/keep.txt") == b"keep"


def test_upload_size_limit_does_not_leave_objects(
    client: TestClient,
    testuser_token_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id = _create_task(client, testuser_token_headers)
    monkeypatch.setattr(settings, "UPLOAD_FILE_MAX_SIZE", 2)
    response = client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        headers=testuser_token_headers,
        files={"file": ("large.txt", b"abc", "text/plain")},
    )
    assert response.status_code == 413
    assert not get_storage_backend().exists(f"upload/{task_id}/large.txt")


def test_database_failure_removes_uploaded_objects(
    client: TestClient,
    testuser_token_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id = _create_task(client, testuser_token_headers)
    monkeypatch.setattr(
        crud_attachment, "create", Mock(side_effect=RuntimeError("test insert failure"))
    )
    content = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(content, format="PNG")
    response = client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        headers=testuser_token_headers,
        files={"file": ("failed.png", content.getvalue(), "image/png")},
    )
    assert response.status_code == 500
    storage = get_storage_backend()
    assert not storage.exists(f"upload/{task_id}/failed.png")
    assert not storage.exists(f"upload/{task_id}/failed-thumbnail.png")


def test_cleanup_failure_does_not_replace_upload_error(
    client: TestClient,
    testuser_token_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id = _create_task(client, testuser_token_headers)
    storage = get_storage_backend()
    monkeypatch.setattr(
        storage, "save_file", Mock(side_effect=HTTPException(413, "test limit"))
    )
    monkeypatch.setattr(
        storage, "delete", Mock(side_effect=RuntimeError("test cleanup failure"))
    )
    response = client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        headers=testuser_token_headers,
        files={"file": ("failed.txt", b"x", "text/plain")},
    )
    assert response.status_code == 413
    assert "test limit" in response.text


def test_delete_external_reference_does_not_require_global_upload_storage(
    client: TestClient,
    testuser_token_headers: dict,
    db: Session,
    monkeypatch,
):
    from backend.application.service import attachment as service
    from backend.domain.models.attachment import TaskAttachment

    task_id = _create_task(client, testuser_token_headers)
    with begin_transaction(db):
        item = crud_attachment.create(
            db,
            TaskAttachment(
                task_id=task_id,
                data_source_id=1,
                filename="external.png",
                path="source/external.png",
            ),
        )
        attachment_id = item.id
    monkeypatch.setattr(
        service,
        "get_storage_backend",
        Mock(side_effect=AssertionError("global storage accessed")),
    )
    response = client.request(
        "DELETE",
        f"/api/v1/tasks/{task_id}/attachments",
        headers=testuser_token_headers,
        json={"attachment_ids": [attachment_id]},
    )
    assert response.status_code == 200
    assert crud_attachment.get(db, attachment_id) is None
