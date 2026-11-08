"""将任务图片与人工标注同步到本地 YOLO 数据集目录。"""

import json
from io import BytesIO
from pathlib import PurePosixPath

import yaml
from fastapi import HTTPException
from loguru import logger
from PIL import Image
from sqlalchemy.orm import Session

from backend.common.storage import LocalStorage, get_storage
from backend.domain.models.sample import DatasetSplit, SampleState, TaskSample
from backend.domain.models.task import Task


def dataset_classes(config: dict) -> list[dict]:
    """按配置顺序返回检测类别，顺序决定 YOLO 类别编号。"""
    tools = config.get("tools", [])
    if any(tool["tool"] != "rectTool" for tool in tools):
        raise HTTPException(422, "当前 YOLO 数据集使用图片矩形框标注")

    attributes = list(config.get("attributes", []))
    for tool in tools:
        attributes.extend(tool.get("config", {}).get("attributes", []))
    if not attributes:
        raise HTTPException(422, "请配置目标检测类别")
    return attributes


def _image_name(sample: TaskSample) -> str:
    return f"{sample.id}{PurePosixPath(sample.file.filename).suffix.lower()}"


def _label_text(result: dict, classes: list[dict], width: int, height: int) -> str:
    """裁剪并归一化有效框；背景样本返回空标签，非法框返回 422。"""
    class_ids = {attribute["value"]: index for index, attribute in enumerate(classes)}
    lines = []
    for box in result.get("rectTool", {}).get("result", []):
        if not box.get("valid", True):
            continue
        x1, y1 = max(0, box["x"]), max(0, box["y"])
        x2 = min(width, box["x"] + box["width"])
        y2 = min(height, box["y"] + box["height"])
        if x2 <= x1 or y2 <= y1:
            raise HTTPException(422, "标注框必须与图片相交并具有正的宽高")
        if box["label"] not in class_ids:
            raise HTTPException(422, "标注类别不在当前任务配置中")
        lines.append(
            f"{class_ids[box['label']]} {(x1 + x2) / (2 * width):.8f} "
            f"{(y1 + y2) / (2 * height):.8f} {(x2 - x1) / width:.8f} "
            f"{(y2 - y1) / height:.8f}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _write_sample(
    storage: LocalStorage, prefix: str, sample: TaskSample, classes: list[dict]
) -> None:
    """同步一个完成样本；跳过或删除的样本移除训练副本。"""
    image_key = f"{prefix}images/{_image_name(sample)}"
    label_key = f"{prefix}labels/{sample.id}.txt"
    if sample.deleted_at or sample.state != SampleState.DONE.value:
        storage.delete(image_key)
        storage.delete(label_key)
        return

    # 1. 原图与标注使用相同旋转方向，再按照实际图片尺寸归一化。
    content = storage.read_bytes(sample.file.path)
    result = json.loads(json.loads(sample.data)["result"])
    with Image.open(BytesIO(content)) as original:
        image_format = original.format
        if result.get("rotate"):
            image = original.rotate(result["rotate"], expand=True)
            try:
                buffer = BytesIO()
                image.save(buffer, format=image_format)
                content = buffer.getvalue()
                width, height = image.size
            finally:
                image.close()
        else:
            width, height = original.size
    label = _label_text(result, classes, width, height)

    # 2. 当前样本标签校验通过后才写入本地目录，背景图片保留空标签。
    storage.save_bytes(content, image_key)
    storage.save_bytes(label.encode("utf-8"), label_key)


def sync_dataset(
    db: Session, task: Task, changed_samples: list[TaskSample] | None = None
) -> None:
    """同步变更图片及训练、测试清单；YOLO 验证与测试使用同一清单。"""
    if not task.config:
        return

    # 1. 类别和目录仅从任务取得，根目录由服务端统一提供。
    classes = dataset_classes(json.loads(task.config))
    prefix = f"{task.dataset_prefix}/"
    samples = (
        db.query(TaskSample)
        .filter(TaskSample.task_id == task.id, TaskSample.deleted_at.is_(None))
        .order_by(TaskSample.id)
        .all()
    )
    storage = get_storage()
    try:
        # 2. 标注变化只重写相关图片；配置变化时重写全部类别编号。
        for sample in samples if changed_samples is None else changed_samples:
            _write_sample(storage, prefix, sample, classes)

        # 3. 只维护 train.txt 和 test.txt，未完成人工确认的样本不进入清单。
        for split in DatasetSplit:
            lines = [
                f"images/{_image_name(sample)}"
                for sample in samples
                if sample.state == SampleState.DONE.value
                and sample.split == split.value
            ]
            listing = "\n".join(lines) + ("\n" if lines else "")
            storage.save_bytes(listing.encode("utf-8"), f"{prefix}{split.value}.txt")
        data = {
            "path": ".",
            "train": "train.txt",
            "val": "test.txt",
            "test": "test.txt",
            "names": [attribute["key"] for attribute in classes],
        }
        storage.save_bytes(
            yaml.safe_dump(data, allow_unicode=True).encode("utf-8"),
            f"{prefix}data.yaml",
        )
    except OSError:
        logger.error("YOLO dataset synchronization failed: task_id={}", task.id)
        raise HTTPException(
            500, "标注已保存，本地数据集同步失败，请重新保存重试"
        ) from None
