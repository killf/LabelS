from typing import List, Union

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query, status, Security
from fastapi.security import HTTPAuthorizationCredentials

from backend.common import db as db_module
from backend.common.security import security
from backend.common.error_code import ErrorCode
from backend.common.error_code import LabelSException
from backend.domain.models.user import User
from backend.dependencies.user import get_current_user
from backend.application.service import sample as service
from backend.application.service import auto_label as auto_label_service
from backend.application.command.sample import PatchSampleCommand
from backend.application.command.sample import CreateSampleCommand
from backend.application.command.sample import DeleteSampleCommand
from backend.application.response.base import OkResp
from backend.application.response.base import MetaData
from backend.application.response.base import CommonDataResp
from backend.application.response.base import OkRespWithMeta
from backend.application.response.sample import SampleResponse
from backend.application.response.sample import CreateSampleResponse
from backend.application.response.auto_label import (
    AutoLabelResponse,
    AutoLabelJobResponse,
)

router = APIRouter(prefix="/tasks", tags=["samples"])


@router.post(
    "/{task_id}/samples",
    response_model=OkResp[CreateSampleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create(
    task_id: int,
    cmd: List[CreateSampleCommand],
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a sample.
    """

    # business logic
    data = await service.create(
        db=db, task_id=task_id, cmd=cmd, current_user=current_user
    )

    # response
    return OkResp[CreateSampleResponse](data=data)


@router.get(
    "/{task_id}/samples",
    response_model=OkRespWithMeta[List[SampleResponse]],
    status_code=status.HTTP_200_OK,
)
async def list_by(
    task_id: int,
    after: Union[int, None] = Query(default=None, gt=0),
    before: Union[int, None] = Query(default=None, gt=0),
    page: Union[int, None] = Query(default=None, ge=0),
    size: Union[int, None] = 100,
    sort: Union[str, None] = Query(
        default=None,
        pattern=r"^(annotated_count|state|inner_id|updated_at):(desc|asc)"
        r"(,(annotated_count|state|inner_id|updated_at):(desc|asc))*$",
    ),
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a annotation result.
    """

    if len([i for i in (after, before, page) if i != None]) != 1:
        raise LabelSException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.CODE_55000_SAMPLE_LIST_PARAMETERS_ERROR,
        )

    # business logic
    data, total = await service.list_by(
        db=db,
        task_id=task_id,
        after=after,
        before=before,
        page=page,
        size=size,
        sorting=sort,
        current_user=current_user,
    )

    # response
    meta_data = MetaData(total=total, page=page, size=len(data))
    return OkRespWithMeta[List[SampleResponse]](meta_data=meta_data, data=data)


@router.get(
    "/{task_id}/samples/{sample_id}",
    response_model=OkResp[SampleResponse],
    status_code=status.HTTP_200_OK,
)
async def get(
    task_id: int,
    sample_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a annotation result.
    """

    # business logic
    data = await service.get(
        db=db, task_id=task_id, sample_id=sample_id, current_user=current_user
    )

    # response
    return OkResp[SampleResponse](data=data)


@router.patch(
    "/{task_id}/samples/{sample_id}",
    response_model=OkResp[SampleResponse],
    status_code=status.HTTP_200_OK,
)
async def update(
    task_id: int,
    sample_id: int,
    cmd: PatchSampleCommand,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    update a annotation.
    """

    # business logic
    data = await service.patch(
        db=db, task_id=task_id, sample_id=sample_id, cmd=cmd, current_user=current_user
    )

    # response
    return OkResp[SampleResponse](data=data)


@router.post(
    "/{task_id}/samples/{sample_id}/auto_label",
    response_model=OkResp[AutoLabelResponse],
    status_code=status.HTTP_200_OK,
)
async def auto_label(
    task_id: int,
    sample_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    data = await auto_label_service.create(
        db=db,
        task_id=task_id,
        sample_id=sample_id,
        current_user=current_user,
    )
    return OkResp[AutoLabelResponse](data=data)


@router.post(
    "/{task_id}/auto_label_job",
    response_model=OkResp[AutoLabelJobResponse],
    status_code=status.HTTP_200_OK,
)
async def create_auto_label_job(
    task_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    data = await auto_label_service.create_batch_job(
        db=db,
        task_id=task_id,
        current_user=current_user,
    )
    return OkResp[AutoLabelJobResponse](data=data)


@router.get(
    "/{task_id}/auto_label_job/{job_id}",
    response_model=OkResp[AutoLabelJobResponse],
    status_code=status.HTTP_200_OK,
)
async def get_auto_label_job_status(
    task_id: int,
    job_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    data = auto_label_service.get_batch_job(
        db=db, task_id=task_id, job_id=job_id, user=current_user
    )
    return OkResp[AutoLabelJobResponse](data=data)


@router.delete(
    "/{task_id}/samples",
    response_model=OkResp[CommonDataResp],
    status_code=status.HTTP_200_OK,
)
async def delete(
    cmd: DeleteSampleCommand,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    delete a annotation.
    """

    # business logic
    data = await service.delete(
        db=db, sample_ids=cmd.sample_ids, current_user=current_user
    )

    # response
    return OkResp[CommonDataResp](data=data)
