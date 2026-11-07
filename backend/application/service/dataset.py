"""把图片标注保存为 S3 上可直接用于训练的 YOLO 数据集。"""

import json
from io import BytesIO
from pathlib import PurePosixPath

import yaml
from botocore.exceptions import BotoCoreError, ClientError
from botocore.client import BaseClient
from fastapi import HTTPException
from loguru import logger
from PIL import Image
from sqlalchemy.orm import Session

from backend.adapter.persistence import crud_datasource
from backend.application.service.access import assert_owner
from backend.application.service.datasource import _build_s3_client
from backend.common.storage import get_storage_backend
from backend.domain.models.data_source import DataSource
from backend.domain.models.sample import DatasetSplit, SampleState, TaskSample
from backend.domain.models.task import Task
from backend.domain.models.user import User


def assert_dataset_destination(db: Session, data_source_id: int, user: User) -> None:
    """任务只能选用创建者自己的数据源作为数据集目标。"""
    source = crud_datasource.get(db=db, ds_id=data_source_id)
    if source is None:
        raise HTTPException(404, "数据集的 S3 数据源不存在")
    assert_owner(source, user)


def dataset_classes(config: dict) -> list[dict]:
    """类别顺序同时用于 YOLO 类别编号和 data.yaml，修改配置时整体同步。"""
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
    # 样本 ID 避免不同源目录中的同名图片互相覆盖。
    return f"{sample.id}{PurePosixPath(sample.file.filename).suffix.lower()}"


def _label_text(result: dict, classes: list[dict], width: int, height: int) -> str:
    """裁剪并归一化有效矩形框；背景样本返回空标签，非法框返回 422。"""
    class_ids = {attribute["value"]: index for index, attribute in enumerate(classes)}
    lines = []
    for box in result.get("rectTool", {}).get("result", []):
        if not box.get("valid", True):
            continue
        x1 = max(0, box["x"])
        y1 = max(0, box["y"])
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
    client: BaseClient,
    source: DataSource,
    prefix: str,
    sample: TaskSample,
    classes: list[dict],
) -> None:
    """读取已完成样本并写入 YOLO 图片和标签，其他状态移除训练对象。"""
    image_key = f"{prefix}images/{_image_name(sample)}"
    label_key = f"{prefix}labels/{sample.id}.txt"
    if sample.deleted_at or sample.state != SampleState.DONE.value:
        client.delete_object(Bucket=source.bucket, Key=image_key)
        client.delete_object(Bucket=source.bucket, Key=label_key)
        return

    # 1. 从附件所属的 S3 读取原图；外部数据源只读取，不修改源对象。
    attachment = sample.file
    if attachment.data_source_id:
        origin = attachment.data_source
        origin_client = _build_s3_client(origin)
        response = origin_client.get_object(Bucket=origin.bucket, Key=attachment.path)
        with response["Body"] as body:
            content = body.read()
    else:
        content = get_storage_backend().read_bytes(attachment.path)

    # 2. 图片与框使用同一旋转方向，再按实际图片尺寸归一化框坐标。
    result = json.loads(json.loads(sample.data)["result"])
    with Image.open(BytesIO(content)) as image:
        image_format = image.format
        if result.get("rotate"):
            image = image.rotate(result["rotate"], expand=True)
            buffer = BytesIO()
            image.save(buffer, format=image_format)
            content = buffer.getvalue()
        width, height = image.size

    label_text = _label_text(result, classes, width, height)

    # 3. 背景图片保留空标签文件，图片和标签统一使用样本 ID 命名。
    client.put_object(
        Bucket=source.bucket,
        Key=image_key,
        Body=content,
        ContentType=Image.MIME[image_format],
    )
    client.put_object(
        Bucket=source.bucket,
        Key=label_key,
        Body=label_text.encode("utf-8"),
        ContentType="text/plain",
    )


def sync_dataset(
    db: Session, task: Task, changed_samples: list[TaskSample] | None = None
) -> None:
    """保存后同步变更样本及划分清单；配置变化时重新同步全部样本。"""
    if not task.config:
        return

    # 1. 从任务配置取得目标目录和类别，不维护额外的同步任务或状态文件。
    classes = dataset_classes(json.loads(task.config))
    source = crud_datasource.get(db=db, ds_id=task.dataset_data_source_id)
    if source is None:
        raise HTTPException(404, "数据集的 S3 数据源不存在")
    prefix = "/".join(
        part.strip("/")
        for part in (source.prefix or "", task.dataset_prefix)
        if part.strip("/")
    )
    prefix = f"{prefix}/" if prefix else ""
    samples = (
        db.query(TaskSample)
        .filter(TaskSample.task_id == task.id, TaskSample.deleted_at.is_(None))
        .order_by(TaskSample.id)
        .all()
    )
    client = _build_s3_client(source)

    try:
        # 2. 只重写本次变化的图片和标签；任务配置变化时整体重写类别编号。
        for sample in samples if changed_samples is None else changed_samples:
            _write_sample(client, source, prefix, sample, classes)

        # 3. 三个清单只包含已完成的样本，训练端可直接下载标准 YOLO 目录。
        for split in DatasetSplit:
            lines = [
                f"images/{_image_name(sample)}"
                for sample in samples
                if sample.state == SampleState.DONE.value
                and sample.split == split.value
            ]
            client.put_object(
                Bucket=source.bucket,
                Key=f"{prefix}{split.value}.txt",
                Body=("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"),
                ContentType="text/plain",
            )

        data = {
            "path": ".",
            "train": "train.txt",
            "val": "val.txt",
            "test": "test.txt",
            "names": [attribute["key"] for attribute in classes],
        }
        client.put_object(
            Bucket=source.bucket,
            Key=f"{prefix}data.yaml",
            Body=yaml.safe_dump(data, allow_unicode=True).encode("utf-8"),
            ContentType="application/yaml",
        )
    except (BotoCoreError, ClientError):
        # 不记录凭据或签名 URL；标注已写入 SQLite，可重新保存以重试同步。
        logger.error("YOLO dataset synchronization failed: task_id={}", task.id)
        raise HTTPException(
            502, "标注已保存，S3 数据集同步失败，请重新保存重试"
        ) from None
