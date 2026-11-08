from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.common.storage import get_storage


def test_local_file_round_trip(tmp_path: Path):
    storage = get_storage()
    file = tmp_path / "sample.txt"
    file.write_text("标注数据", encoding="utf-8")
    storage.save_file(file, "tasks/1/uploads/sample.txt")
    assert storage.read_text("tasks/1/uploads/sample.txt") == "标注数据"
    assert storage.exists("tasks/1/uploads/sample.txt")
    storage.delete("tasks/1/uploads/sample.txt")
    assert not storage.exists("tasks/1/uploads/sample.txt")


@pytest.mark.parametrize(
    "key",
    ["../outside.txt", "/outside.txt", "tasks/../../outside.txt", "C:\\outside.txt"],
)
def test_storage_rejects_paths_outside_root(key):
    with pytest.raises(ValueError):
        get_storage().path(key)


def test_preview_signature_is_bound_to_path_and_expiration():
    storage = get_storage()
    key = "tasks/1/uploads/image.png"
    url = storage.get_read_url(key)
    query = parse_qs(urlsplit(url).query)
    expires = int(query["expires"][0])
    signature = query["signature"][0]
    assert storage.verify_read_url(key, expires, signature)
    assert not storage.verify_read_url("tasks/2/uploads/image.png", expires, signature)
    assert not storage.verify_read_url(key, expires - 86400, signature)
    assert not storage.verify_read_url(key, expires, "modified")
    with pytest.raises(ValueError):
        storage.get_read_url("tasks/1/models/model.pt")


def test_default_database_follows_data_directory(tmp_path):
    from backend.common.config import Settings

    configured = Settings(BASE_DATA_DIR=str(tmp_path), DATABASE_URL="")
    assert configured.DATABASE_URL == f"sqlite:///{tmp_path.as_posix()}/labels.sqlite"
    explicit = Settings(BASE_DATA_DIR=str(tmp_path), DATABASE_URL="sqlite:///:memory:")
    assert explicit.DATABASE_URL == "sqlite:///:memory:"
