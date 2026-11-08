from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.application.command.training import StartTrainingCommand
from backend.application.response.base import (
    CommonDataResp,
    MetaData,
    OkResp,
    OkRespWithMeta,
)
from backend.application.response.training import TrainingRunResponse
from backend.application.service import training as service
from backend.common.db import get_db
from backend.dependencies.user import get_current_user
from backend.domain.models.user import User

router = APIRouter(prefix="/tasks/{task_id}/training-runs", tags=["training"])


@router.post("", response_model=OkResp[TrainingRunResponse], status_code=202)
async def start(
    task_id: int,
    cmd: StartTrainingCommand,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return OkResp[TrainingRunResponse](data=await service.start(db, task_id, cmd, user))


@router.get("", response_model=OkRespWithMeta[list[TrainingRunResponse]])
async def list_runs(
    task_id: int,
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    runs, total = service.list_runs(db, task_id, user, page, size)
    return OkRespWithMeta[list[TrainingRunResponse]](
        data=runs, meta_data=MetaData(total=total, page=page, size=len(runs))
    )


@router.get("/{run_id}", response_model=OkResp[TrainingRunResponse])
async def get_run(
    task_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return OkResp[TrainingRunResponse](data=service.get_run(db, task_id, run_id, user))


@router.get("/{run_id}/log", response_class=PlainTextResponse)
async def get_log(
    task_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return PlainTextResponse(service.get_log(db, task_id, run_id, user))


@router.delete("/{run_id}/log", response_model=OkResp[CommonDataResp])
async def clear_logs(
    task_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.clear_logs(db, task_id, run_id, user)
    return OkResp[CommonDataResp](data=CommonDataResp(ok=True))


@router.delete("/{run_id}", response_model=OkResp[CommonDataResp])
async def delete_run(
    task_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.delete_run(db, task_id, run_id, user)
    return OkResp[CommonDataResp](data=CommonDataResp(ok=True))
