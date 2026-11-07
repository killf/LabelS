"""使用任务数据集 models/ 下的 YOLO 权重生成可人工修改的预标注。"""

import asyncio
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from loguru import logger
from PIL import Image
from sqlalchemy.orm import Session

from labelu.internal.adapter.persistence import (
    crud_auto_label_job, crud_datasource, crud_pre_annotation, crud_sample, crud_task,
)
from labelu.internal.application.response.auto_label import AutoLabelResponse, AutoLabelJobResponse
from labelu.internal.application.service.access import assert_task_access
from labelu.internal.application.service.dataset import dataset_classes
from labelu.internal.application.service.datasource import _build_s3_client
from labelu.internal.common.config import settings
from labelu.internal.common.db import SessionLocal, begin_transaction
from labelu.internal.common.storage import get_storage_backend
from labelu.internal.domain.models.auto_label_job import AutoLabelJob, AutoLabelStatus
from labelu.internal.domain.models.pre_annotation import TaskPreAnnotation
from labelu.internal.domain.models.sample import TaskSample
from labelu.internal.domain.models.task import Task
from labelu.internal.domain.models.user import User


def _task(db: Session, task_id: int, user: User) -> Task:
    task = crud_task.get(db=db, task_id=task_id)
    if task is None:
        raise HTTPException(404, "标注任务不存在")
    assert_task_access(task, user)
    return task


def _model_storage(db: Session, task: Task) -> tuple[Any, str, str]:
    source = crud_datasource.get(db=db, ds_id=task.dataset_data_source_id)
    if source is None:
        raise HTTPException(400, "请先配置数据集 S3 数据源")
    parts = (source.prefix or "", task.dataset_prefix, "models")
    prefix = "/".join(part.strip("/") for part in parts if part.strip("/")) + "/"
    return _build_s3_client(source), source.bucket, prefix


def list_models(db: Session, task_id: int, user: User) -> list[str]:
    task = _task(db, task_id, user)
    client, bucket, prefix = _model_storage(db, task)
    names = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix, Delimiter="/"
    ):
        names.extend(PurePosixPath(obj["Key"]).name for obj in page.get("Contents", [])
                     if obj["Key"].endswith(".pt"))
    return sorted(names, reverse=True)


@contextmanager
def _load_model(db: Session, task: Task, model_name: str) -> Iterator[Any]:
    if not settings.AI_AUTO_LABEL_ENABLED:
        raise HTTPException(400, "AI 标注未启用")
    if not model_name:
        raise HTTPException(400, "请在任务配置中选择 AI 模型")
    if PurePosixPath(model_name).name != model_name or not model_name.endswith(".pt"):
        raise HTTPException(422, "请选择 models/ 目录下的权重文件")

    # 1. 使用现有训练环境中的 Ultralytics，不在请求中安装依赖或下载官方权重。
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    try:
        from ultralytics import YOLO
    except ImportError:
        raise HTTPException(503, "AI 标注需要 Ultralytics，请使用已安装训练依赖的 Python 环境") from None

    # 2. 权重仅在本次单张或批量推理期间保存在临时目录。
    client, bucket, prefix = _model_storage(db, task)
    with tempfile.TemporaryDirectory(prefix="labelu-yolo-") as directory:
        weights = Path(directory) / model_name
        try:
            client.download_file(bucket, prefix + model_name, str(weights))
        except (BotoCoreError, ClientError):
            raise HTTPException(502, "无法从 S3 读取所选模型权重") from None
        yield YOLO(str(weights))


def _image_content(sample: TaskSample) -> bytes:
    attachment = sample.file
    if not attachment.data_source_id:
        return get_storage_backend().read_bytes(attachment.path)
    source = attachment.data_source
    response = _build_s3_client(source).get_object(Bucket=source.bucket, Key=attachment.path)
    with response["Body"] as body:
        return body.read()


def _predict(model: Any, sample: TaskSample, task: Task, model_name: str) -> dict:
    # 1. 类别显示名和内部值均可匹配，覆盖训练 data.yaml 与标注工具的命名差异。
    attributes = dataset_classes(json.loads(task.config))
    labels = {name: attribute["value"] for attribute in attributes
              for name in (attribute["key"], attribute["value"])}
    started = time.perf_counter()
    with Image.open(BytesIO(_image_content(sample))) as image:
        prediction = model.predict(image, imgsz=1024, conf=0.25,
                                   device=settings.AI_DEVICE or None, verbose=False)[0]

    # 2. 只生成任务已配置类别的矩形框；预标注不改变样本的人工完成状态。
    boxes = []
    unmatched = 0
    for coordinates, class_id, confidence in zip(
        prediction.boxes.xyxy.tolist(), prediction.boxes.cls.tolist(),
        prediction.boxes.conf.tolist(),
    ):
        name = prediction.names[int(class_id)]
        if name not in labels:
            unmatched += 1
            continue
        x1, y1, x2, y2 = coordinates
        boxes.append({"id": str(uuid.uuid4()), "order": len(boxes) + 1,
                      "label": labels[name], "valid": True, "isVisible": True,
                      "x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1,
                      "attributes": {"score": str(confidence)}})

    warning = f"已忽略 {unmatched} 个未匹配任务类别的预测框" if unmatched else None
    return {"sample_name": sample.file.filename,
            "annotations": {"rectTool": {"toolName": "rectTool", "result": boxes}},
            "config": {"rectTool": attributes},
            "meta": {"source_type": "ai_generated", "provider": "yolo",
                     "model": model_name, "sample_id": sample.id,
                     "latency_ms": int((time.perf_counter() - started) * 1000),
                     "warning_message": warning}}


def _save_prediction(db: Session, task: Task, sample: TaskSample,
                     payload: dict, user_id: int) -> int:
    existing, _ = crud_pre_annotation.list_by(
        db=db, task_id=task.id, sample_name=sample.file.filename, page=0, size=None
    )
    # 仅替换当前样本的 AI 结果，保留人工导入的预标注和同名的其他样本。
    previous_ai = [item.id for item in existing
                   if json.loads(item.data).get("meta", {}).get("source_type") == "ai_generated"
                   and json.loads(item.data).get("meta", {}).get("sample_id") == sample.id]
    with begin_transaction(db):
        if previous_ai:
            crud_pre_annotation.delete(db=db, pre_annotation_ids=previous_ai)
        created = crud_pre_annotation.batch(db=db, pre_annotations=[TaskPreAnnotation(
            task_id=task.id, sample_name=sample.file.filename,
            data=json.dumps(payload, ensure_ascii=False), created_by=user_id, updated_by=user_id,
        )])
    return created[0].id


def _single(db: Session, task_id: int, sample_id: int,
            user: User) -> AutoLabelResponse:
    task = _task(db, task_id, user)
    sample = crud_sample.get(db=db, sample_id=sample_id)
    if sample is None or sample.task_id != task_id or not sample.file:
        raise HTTPException(404, "标注样本不存在")

    try:
        with _load_model(db, task, task.ai_model_name) as model:
            payload = _predict(model, sample, task, task.ai_model_name)
    except HTTPException:
        raise
    except Exception as error:
        logger.error("YOLO prediction failed: task_id={}, sample_id={}, error={}",
                     task_id, sample_id, type(error).__name__)
        raise HTTPException(502, "YOLO 预标注失败，请检查权重与运行环境") from None
    annotation_id = _save_prediction(db, task, sample, payload, user.id)
    return AutoLabelResponse(status="COMPLETED", task_id=task.id, sample_id=sample.id,
        media_type=task.media_type, provider="yolo", model=task.ai_model_name,
        pre_annotation_id=annotation_id, latency_ms=payload["meta"]["latency_ms"],
        warning_message=payload["meta"]["warning_message"])


async def create(db: Session, task_id: int, sample_id: int,
                 current_user: User) -> AutoLabelResponse:
    # 推理在线程中执行，保持页面 API 和批量进度查询可响应。
    return await asyncio.to_thread(_single, db, task_id, sample_id, current_user)


async def create_batch_job(db: Session, task_id: int,
                           current_user: User) -> AutoLabelJobResponse:
    task = _task(db, task_id, current_user)
    if not settings.AI_AUTO_LABEL_ENABLED or not task.ai_model_name:
        raise HTTPException(400, "请启用 AI 标注并在任务配置中选择模型")
    dataset_classes(json.loads(task.config))
    sample_ids = [sample.id for sample in crud_sample.list_new_samples(db=db, task_id=task_id)]
    if not sample_ids:
        raise HTTPException(400, "没有待标注样本")

    with begin_transaction(db):
        job = crud_auto_label_job.create(db=db, task_id=task_id, user_id=current_user.id,
                                         sample_count=len(sample_ids), model_name=task.ai_model_name)
        job_id = job.id

    asyncio.get_running_loop().run_in_executor(None, _run_batch, job_id, sample_ids)
    return get_batch_job(db, task_id, job_id, current_user)


def get_batch_job(db: Session, task_id: int, job_id: int, user: User) -> AutoLabelJobResponse:
    _task(db, task_id, user)
    job = crud_auto_label_job.get(db=db, job_id=job_id)
    if job is None or job.task_id != task_id:
        raise HTTPException(404, "AI 标注任务不存在")
    return AutoLabelJobResponse.model_validate(job, from_attributes=True)


def _run_batch(job_id: int, sample_ids: list[int]) -> None:
    with SessionLocal() as db:
        job = crud_auto_label_job.get(db=db, job_id=job_id)
        try:
            # 1. 每批只加载一次权重，逐张推理并保存预标注。
            with begin_transaction(db):
                crud_auto_label_job.update_status(db, job, AutoLabelStatus.PROCESSING.value)
            task = crud_task.get(db=db, task_id=job.task_id)
            with _load_model(db, task, job.model_name) as model:
                for sample_id in sample_ids:
                    sample = crud_sample.get(db=db, sample_id=sample_id)
                    if sample is None or sample.state != "NEW":
                        with begin_transaction(db):
                            crud_auto_label_job.increment_progress(db, job, success=False)
                        continue
                    try:
                        payload = _predict(model, sample, task, job.model_name)
                        _save_prediction(db, task, sample, payload, job.created_by)
                        success = True
                    except Exception as error:
                        db.rollback()
                        logger.error("YOLO prediction failed: job_id={}, sample_id={}, error={}",
                                     job_id, sample_id, type(error).__name__)
                        success = False
                    with begin_transaction(db):
                        crud_auto_label_job.increment_progress(db, job, success=success)

            # 2. 部分失败也明确显示失败数量，已成功的预标注仍可人工检查。
            with begin_transaction(db):
                state = AutoLabelStatus.FAILED if job.failed_count else AutoLabelStatus.COMPLETED
                message = f"{job.failed_count} 个样本预标注失败" if job.failed_count else None
                crud_auto_label_job.update_status(db, job, state.value, error_message=message)
        except Exception as error:
            db.rollback()
            logger.error("YOLO batch failed: job_id={}, error={}", job_id, type(error).__name__)
            message = error.detail if isinstance(error, HTTPException) else "YOLO 批量标注失败，请检查权重与运行环境"
            with begin_transaction(db):
                crud_auto_label_job.update_status(db, job, AutoLabelStatus.FAILED.value,
                                                  error_message=message)


def fail_interrupted_jobs() -> None:
    """服务重启后把未完成的后台批次标为中断，不自动重跑模型。"""
    with SessionLocal() as db, db.begin():
        db.query(AutoLabelJob).filter(AutoLabelJob.status.in_(["PENDING", "PROCESSING"])).update({
            AutoLabelJob.status: "FAILED", AutoLabelJob.error_message: "服务重启，批量标注已中断，请重新发起",
        }, synchronize_session=False)
