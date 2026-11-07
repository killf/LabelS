from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from labelu.internal.common.storage import get_storage_backend


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
