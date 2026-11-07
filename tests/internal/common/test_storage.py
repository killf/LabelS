from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from labelu.internal.common.storage import get_storage_backend


def test_s3_roundtrip_and_missing_object(tmp_path: Path) -> None:
    storage = get_storage_backend()
    file = tmp_path / "sample.txt"
    file.write_text("标注数据", encoding="utf-8")

    storage.save_file(file, "upload/sample.txt", "text/plain")
    assert storage.read_text("upload/sample.txt") == "标注数据"
    assert storage.exists("upload/sample.txt")
    assert "upload/sample.txt" in storage.get_read_url("upload/sample.txt")

    storage.delete("upload/sample.txt")
    assert not storage.exists("upload/sample.txt")


def test_s3_permission_error_is_not_reported_as_missing() -> None:
    storage = get_storage_backend()
    with Stubber(storage._client) as stub:
        stub.add_client_error(
            "head_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            storage.exists("denied.png")
