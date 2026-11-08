"""在独立 Python 进程中训练，记录状态并提供有访问控制的本地日志。"""

import asyncio
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from backend.adapter.persistence import crud_task
from backend.application.command.training import StartTrainingCommand
from backend.application.response.training import TrainingRunResponse
from backend.application.service.access import assert_task_access
from backend.application.service.dataset import sync_dataset
from backend.common.config import settings
from backend.common.db import SessionLocal, begin_transaction
from backend.common.storage import get_storage
from backend.domain.models.sample import SampleState, TaskSample
from backend.domain.models.task import Task
from backend.domain.models.training_run import TrainingRun, TrainingStatus
from backend.domain.models.auto_label_job import AutoLabelJob
from backend.domain.models.user import User

OFFICIAL_MODELS = {f"yolo26{size}.pt" for size in "nsmlx"}
_workers: set[asyncio.Task] = set()


def _task(db: Session, task_id: int, user: User) -> Task:
    task = crud_task.get(db, task_id)
    if task is None:
        raise HTTPException(404, "标注任务不存在")
    assert_task_access(task, user)
    return task


def _response(run: TrainingRun) -> TrainingRunResponse:
    return TrainingRunResponse(
        id=run.id,
        task_id=run.task_id,
        created_by=run.created_by,
        initial_model=run.initial_model,
        parameters=json.loads(run.parameters),
        status=run.status,
        run_id=run.run_id,
        model_name=run.model_name,
        model_available=bool(
            run.model_name
            and get_storage()
            .path(f"tasks/{run.task_id}/models/{run.model_name}")
            .is_file()
        ),
        log_available=(_workspace(run.task_id, run.id) / "console.log").is_file(),
        metrics=json.loads(run.metrics or "{}"),
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def list_runs(
    db: Session, task_id: int, user: User, page: int, size: int
) -> tuple[list[TrainingRunResponse], int]:
    """验证任务访问权，按发起时间倒序返回训练记录与总数。"""
    _task(db, task_id, user)
    query = db.query(TrainingRun).filter(TrainingRun.task_id == task_id)
    return [
        _response(run)
        for run in query.order_by(TrainingRun.id.desc()).offset(page * size).limit(size)
    ], query.count()


def get_run(db: Session, task_id: int, run_id: int, user: User) -> TrainingRunResponse:
    _task(db, task_id, user)
    run = db.get(TrainingRun, run_id)
    if run is None or run.task_id != task_id:
        raise HTTPException(404, "训练记录不存在")
    return _response(run)


def model_file(db: Session, task_id: int, name: str, user: User) -> Path:
    """验证任务访问权，只允许下载该任务目录直属的模型文件。"""
    task = _task(db, task_id, user)
    if (
        PurePosixPath(name).name != name
        or PureWindowsPath(name).name != name
        or not name.endswith(".pt")
    ):
        raise HTTPException(422, "无效的模型文件名")
    directory = get_storage().path(f"{task.dataset_prefix}/models")
    file = get_storage().path(f"{task.dataset_prefix}/models/{name}")
    if not file.is_relative_to(directory) or not file.is_file():
        raise HTTPException(404, "模型文件不存在")
    return file


def _cleanup_run(
    db: Session, task_id: int, run_id: int, user: User
) -> tuple[Task, TrainingRun]:
    task = _task(db, task_id, user)
    if task.created_by != user.id:
        raise HTTPException(403, "只有任务创建者可以清理执行记录")
    run = db.get(TrainingRun, run_id)
    if run is None or run.task_id != task_id:
        raise HTTPException(404, "训练记录不存在")
    if run.status in {TrainingStatus.PENDING.value, TrainingStatus.RUNNING.value}:
        raise HTTPException(409, "训练尚未结束，不能清理")
    return task, run


def _remove_logs(task_id: int, run_id: int) -> None:
    """只清理当前任务 runs/ 下的指定执行目录，不删除记录或模型目录。"""
    directory = _workspace(task_id, run_id)
    parent = get_storage().path(f"tasks/{task_id}/runs")
    if not directory.is_relative_to(parent) or directory == parent:
        raise HTTPException(403, "无效的日志目录")
    if directory.exists():
        shutil.rmtree(directory)


def clear_logs(db: Session, task_id: int, run_id: int, user: User) -> None:
    """清理日志和中间文件，保留数据库记录、指标与产出模型。"""
    _cleanup_run(db, task_id, run_id, user)
    try:
        _remove_logs(task_id, run_id)
    except OSError:
        raise HTTPException(500, "日志清理失败，请检查文件权限后重试") from None


def delete_run(db: Session, task_id: int, run_id: int, user: User) -> None:
    """删除执行记录、产出模型和日志；被 AI 或其他训练引用的模型不能清理。"""
    task, run = _cleanup_run(db, task_id, run_id, user)
    model = None
    if run.model_name:
        referenced = task.ai_model_name == run.model_name
        referenced |= (
            db.query(TrainingRun)
            .filter(
                TrainingRun.task_id == task_id,
                TrainingRun.initial_model == run.model_name,
                TrainingRun.status.in_(
                    [TrainingStatus.PENDING.value, TrainingStatus.RUNNING.value]
                ),
            )
            .first()
            is not None
        )
        referenced |= (
            db.query(AutoLabelJob)
            .filter(
                AutoLabelJob.task_id == task_id,
                AutoLabelJob.model_name == run.model_name,
                AutoLabelJob.status.in_(["PENDING", "PROCESSING"]),
            )
            .first()
            is not None
        )
        if referenced:
            raise HTTPException(409, "模型正在使用，请先切换 AI 模型并等待相关任务结束")
        directory = get_storage().path(f"tasks/{task_id}/models")
        model = get_storage().path(f"tasks/{task_id}/models/{run.model_name}")
        if not model.is_relative_to(directory) or model == directory:
            raise HTTPException(403, "无效的模型路径")

    # 文件删除失败时回滚数据库记录，允许用户重试清理。
    try:
        with begin_transaction(db):
            _remove_logs(task_id, run_id)
            if model is not None:
                model.unlink(missing_ok=True)
            db.delete(run)
    except OSError:
        raise HTTPException(500, "执行记录清理失败，请检查文件权限后重试") from None


def _workspace(task_id: int, run_id: int) -> Path:
    return get_storage().path(f"tasks/{task_id}/runs/{run_id}")


def get_log(db: Session, task_id: int, run_id: int, user: User) -> str:
    """仅返回本任务训练日志的末尾 64 KiB，避免轮询读取无限增长的文件。"""
    get_run(db, task_id, run_id, user)
    path = _workspace(task_id, run_id) / "console.log"
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        content = stream.read().decode("utf-8", errors="replace")
    # 终端颜色与进度条控制符不适用于网页文本，原始文件仍保持不变。
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", content).replace("\r", "\n")


async def start(
    db: Session, task_id: int, cmd: StartTrainingCommand, user: User
) -> TrainingRunResponse:
    """检查完成样本和初始模型，保存训练记录后异步启动本机训练。"""
    # 1. 同一任务已有训练时明确返回状态；不创建GPU 预留记录。
    task = _task(db, task_id, user)
    active = (
        db.query(TrainingRun)
        .filter(
            TrainingRun.task_id == task_id,
            TrainingRun.status.in_(
                [TrainingStatus.PENDING.value, TrainingStatus.RUNNING.value]
            ),
        )
        .first()
    )
    if active is not None:
        raise HTTPException(409, "该任务已有训练正在进行，请查看训练记录")
    if importlib.util.find_spec("ultralytics") is None:
        raise HTTPException(503, "当前后端 Python 环境尚未安装训练依赖")
    if not task.config:
        raise HTTPException(422, "请先完成标注配置")
    splits = {
        split
        for (split,) in db.query(TaskSample.split)
        .filter(
            TaskSample.task_id == task_id,
            TaskSample.deleted_at.is_(None),
            TaskSample.state == SampleState.DONE.value,
        )
        .distinct()
    }
    if not {"train", "test"}.issubset(splits):
        raise HTTPException(422, "训练集和测试集都需要至少一张已完成标注的图片")
    storage = get_storage()
    if (
        cmd.initial_model not in OFFICIAL_MODELS
        and cmd.initial_model
        not in storage.list_models(f"{task.dataset_prefix}/models/")
    ):
        raise HTTPException(422, "请选择官方 YOLO26 权重或当前任务已有模型")

    # 2. 训练前同步完整快照；未成功同步时不创建可启动的训练记录。
    sync_dataset(db, task)
    with begin_transaction(db):
        run = TrainingRun(
            task_id=task_id,
            created_by=user.id,
            initial_model=cmd.initial_model,
            parameters=json.dumps(cmd.model_dump()),
            status=TrainingStatus.PENDING.value,
        )
        db.add(run)
        db.flush()
        run_id = run.id
    response = _response(run)
    worker = asyncio.create_task(_run(run_id))
    _workers.add(worker)
    worker.add_done_callback(_workers.discard)
    return response


async def _run(run_id: int) -> None:
    """准备独立工作目录与子进程，保存退出状态和结构化模型产物。"""
    process = None
    with SessionLocal() as db:
        run = db.get(TrainingRun, run_id)
        if run is None:
            return
        try:
            # 1. 任务模型直接使用本地文件，官方权重保存在本次工作目录。
            task = crud_task.get(db, run.task_id)
            if task is None:
                raise RuntimeError("标注任务已不存在")
            workspace = _workspace(run.task_id, run_id)
            workspace.mkdir(parents=True, exist_ok=True)
            model = workspace / run.initial_model
            if run.initial_model not in OFFICIAL_MODELS:
                model = get_storage().path(
                    f"{task.dataset_prefix}/models/{run.initial_model}"
                )
            parameters = json.loads(run.parameters)
            prefix = task.dataset_prefix
            with begin_transaction(db):
                run.status = TrainingStatus.RUNNING.value
                run.started_at = datetime.now()

            # 2. 参数通过数组传入独立进程，不经过 shell，不接收任意用户命令。
            environment = os.environ.copy()
            environment.update(
                {
                    "YOLO_AUTOINSTALL": "false",
                    "PYTHONUNBUFFERED": "1",
                    "YOLO_CONFIG_DIR": str(workspace / "ultralytics"),
                }
            )
            args = [
                sys.executable,
                "-m",
                "backend.training.train",
                "--data",
                str(get_storage().path(prefix)),
                "--work-dir",
                str(workspace),
                "--result-file",
                str(workspace / "result.json"),
                "--model",
                str(model),
                "--epochs",
                str(parameters["epochs"]),
                "--imgsz",
                str(parameters["imgsz"]),
                "--batch",
                str(parameters["batch"]),
                "--workers",
                "0",
            ]
            if settings.AI_DEVICE:
                args.extend(["--device", settings.AI_DEVICE])
            with (workspace / "console.log").open("wb") as output:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    env=environment,
                    stdout=output,
                    stderr=asyncio.subprocess.STDOUT,
                )
                code = await process.wait()

            # 3. 只有训练退出成功且结果文件可读时，记录模型与指标。
            with begin_transaction(db):
                if code == 0:
                    result = json.loads(
                        (workspace / "result.json").read_text(encoding="utf-8")
                    )
                    run.status = TrainingStatus.SUCCEEDED.value
                    run.run_id = result["run_id"]
                    run.model_name = result["model_name"]
                    run.metrics = json.dumps(result["metrics"])
                else:
                    run.status = TrainingStatus.FAILED.value
                    run.error_message = f"训练进程退出码为 {code}，请查看训练日志"
                run.finished_at = datetime.now()
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            with begin_transaction(db):
                run.status = TrainingStatus.INTERRUPTED.value
                run.error_message = "服务关闭，训练已中断"
                run.finished_at = datetime.now()
            raise
        except Exception as error:
            logger.error(
                "Training failed: run_id={}, error={}", run_id, type(error).__name__
            )
            with begin_transaction(db):
                run.status = TrainingStatus.FAILED.value
                run.error_message = "训练执行失败，请查看训练日志与运行环境"
                run.finished_at = datetime.now()


def fail_interrupted_runs() -> None:
    """启动时标记上次未完成的训练，不自动重跑 GPU 任务。"""
    with SessionLocal() as db, db.begin():
        db.query(TrainingRun).filter(
            TrainingRun.status.in_(
                [
                    TrainingStatus.PENDING.value,
                    TrainingStatus.RUNNING.value,
                ]
            )
        ).update(
            {
                TrainingRun.status: TrainingStatus.INTERRUPTED.value,
                TrainingRun.error_message: "服务重启，训练状态已中断，请确认后重新发起",
                TrainingRun.finished_at: datetime.now(),
            }
        )


async def stop_workers() -> None:
    """服务正常关闭时终止自己启动的训练，等待其状态写入完成。"""
    workers = list(_workers)
    for worker in workers:
        worker.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
