import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from backend.training import train


def test_training_help_does_not_load_model_runtime(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["labels-train", "--help"])
    with pytest.raises(SystemExit) as result:
        train.main()
    assert result.value.code == 0
    assert "--data" in capsys.readouterr().out
    assert "torch" not in sys.modules
    assert "ultralytics" not in sys.modules


@pytest.fixture
def local_dataset(tmp_path):
    directory = tmp_path / "task"
    (directory / "images").mkdir(parents=True)
    (directory / "labels").mkdir()
    config = {
        "path": ".",
        "train": "train.txt",
        "val": "test.txt",
        "test": "test.txt",
        "names": ["person"],
        "download": "must-not-execute",
    }
    (directory / "data.yaml").write_text(yaml.safe_dump(config))
    for split in ["train", "test"]:
        Image.new("RGB", (10, 8), "blue").save(directory / "images" / f"{split}.png")
        (directory / f"{split}.txt").write_text(f"images/{split}.png\n")
    (directory / "labels/test.txt").write_text("")
    return directory


def test_local_dataset_snapshot_is_independent(local_dataset, tmp_path):
    target = tmp_path / "snapshot-data"
    originals = tmp_path / "originals"
    config_file = train.prepare_dataset(local_dataset, target, originals)
    config = yaml.safe_load(config_file.read_text())
    assert config["path"] == str(target.resolve())
    assert config["val"] == config["test"] == "test.txt"
    assert "download" not in config
    assert not (target / "val.txt").exists()
    assert "download" in yaml.safe_load((originals / "data.yaml").read_text())
    assert (target / "labels/test.txt").read_bytes() == b""
    assert not (target / "labels/train.txt").exists()
    before = (target / "images/train.png").read_bytes()
    (local_dataset / "images/train.png").write_bytes(b"changed after snapshot")
    assert (target / "images/train.png").read_bytes() == before
    assert (target / "train.txt").read_text().strip() == str(
        (target / "images/train.png").resolve()
    )


def test_snapshot_rejects_traversal(local_dataset, tmp_path):
    (local_dataset / "train.txt").write_text("images/../../outside.png\n")
    with pytest.raises(ValueError, match="Invalid dataset-relative path"):
        train.prepare_dataset(local_dataset, tmp_path / "data-copy", tmp_path / "input")


def test_snapshot_requires_completed_test_images(local_dataset, tmp_path):
    (local_dataset / "test.txt").write_text("")
    with pytest.raises(ValueError, match="test.txt contains no images"):
        train.prepare_dataset(local_dataset, tmp_path / "data-copy", tmp_path / "input")
