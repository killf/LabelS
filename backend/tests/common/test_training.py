import sys
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from PIL import Image

from backend.training import train
from backend.training.storage import S3Storage


def test_training_help_does_not_load_model_runtime(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["labels-train", "--help"])
    with pytest.raises(SystemExit) as result:
        train.main()
    assert result.value.code == 0
    assert "--epochs" in capsys.readouterr().out
    assert "torch" not in sys.modules
    assert "ultralytics" not in sys.modules


@pytest.fixture
def training_store(monkeypatch):
    """使用 conftest 中已隔离的 Moto 桶，写入最小合成训练数据。"""
    monkeypatch.setenv("S3_ENDPOINT", "https://s3.amazonaws.com")
    store = S3Storage("s3://labels-test/training-test/")
    image = BytesIO()
    Image.new("RGB", (10, 8), "blue").save(image, format="PNG")
    config = {
        "path": ".",
        "train": "train.txt",
        "val": "val.txt",
        "test": "test.txt",
        "names": ["object"],
        "download": "never execute dataset scripts",
    }
    objects = {
        "data.yaml": yaml.safe_dump(config).encode(),
        "train.txt": b"images/train.png\n",
        "val.txt": b"images/val.png\n",
        "test.txt": b"",
        "images/train.png": image.getvalue(),
        "images/val.png": image.getvalue(),
        "labels/val.txt": b"",
    }
    for name, content in objects.items():
        store.client.put_object(
            Bucket=store.bucket, Key=store.prefix + name, Body=content
        )
    try:
        yield store
    finally:
        store.close()


def test_prepare_dataset_downloads_without_a_model_runtime(training_store, tmp_path):
    directory = tmp_path / "dataset"
    snapshot = tmp_path / "snapshot"
    config_path, has_test = train.prepare_dataset(training_store, directory, snapshot)
    config = yaml.safe_load(config_path.read_text())
    assert config["path"] == str(directory.resolve())
    assert "download" not in config
    assert "download" in yaml.safe_load((snapshot / "data.yaml").read_text())
    assert not has_test
    assert (directory / "images/train.png").is_file()
    assert (directory / "labels/val.txt").read_bytes() == b""
    assert not (directory / "labels/train.txt").exists()
    assert (directory / "train.txt").read_text().strip() == str(
        (directory / "images/train.png").resolve()
    )


def test_prepare_dataset_rejects_paths_outside_dataset(training_store, tmp_path):
    training_store.client.put_object(
        Bucket=training_store.bucket,
        Key=training_store.prefix + "train.txt",
        Body=b"../escape.png\n",
    )
    with pytest.raises(ValueError, match="Invalid dataset-relative path"):
        train.prepare_dataset(
            training_store, tmp_path / "dataset", tmp_path / "snapshot"
        )
    assert not (tmp_path / "escape.png").exists()
