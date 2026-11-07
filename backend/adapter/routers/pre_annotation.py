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
from backend.application.service import pre_annotation as service
from backend.application.command.pre_annotation import CreatePreAnnotationCommand
from backend.application.command.pre_annotation import DeletePreAnnotationCommand
from backend.application.response.base import OkResp
from backend.application.response.base import MetaData
from backend.application.response.base import CommonDataResp
from backend.application.response.base import OkRespWithMeta
from backend.application.response.pre_annotation import (
    PreAnnotationFileResponse,
    PreAnnotationResponse,
)
from backend.application.response.pre_annotation import CreatePreAnnotationResponse

router = APIRouter(prefix="/tasks", tags=["pre_annotations"])


@router.post(
    "/{task_id}/pre_annotations",
    response_model=OkResp[CreatePreAnnotationResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create(
    task_id: int,
    cmd: List[CreatePreAnnotationCommand],
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a pre_annotation.
    """

    # business logic
    data = await service.create(
        db=db, task_id=task_id, cmd=cmd, current_user=current_user
    )

    # response
    return OkResp[CreatePreAnnotationResponse](data=data)


@router.get(
    "/{task_id}/pre_annotations/files",
    response_model=OkRespWithMeta[List[PreAnnotationFileResponse]],
    status_code=status.HTTP_200_OK,
)
async def list_pre_annotation_files_request(
    task_id: int,
    after: Union[int, None] = Query(default=None, gt=0),
    before: Union[int, None] = Query(default=None, gt=0),
    page: Union[int, None] = Query(default=None, ge=0),
    size: Union[int, None] = 100,
    sort: Union[str, None] = Query(default=None, pattern="(created_at):(desc|asc)"),
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a list of pre annotation files(json or jsonl).
    """

    data, total = await service.list_pre_annotation_files(
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
    return OkRespWithMeta[List[PreAnnotationFileResponse]](
        meta_data=meta_data, data=data
    )


@router.delete(
    "/{task_id}/pre_annotations/files/{file_id}",
    response_model=OkResp[CommonDataResp],
    status_code=status.HTTP_200_OK,
)
async def delete_pre_annotation_file_request(
    task_id: int,
    file_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a pre annotation file(json or jsonl).
    """

    data = await service.delete_pre_annotation_file(
        db=db, task_id=task_id, file_id=file_id, current_user=current_user
    )

    # response
    return OkResp[CommonDataResp](data=data)


@router.get(
    "/{task_id}/pre_annotations",
    response_model=OkRespWithMeta[List[PreAnnotationResponse]],
    status_code=status.HTTP_200_OK,
)
async def list_by(
    task_id: int,
    sample_name: str = Query(default=None, min_length=1, max_length=255),
    after: Union[int, None] = Query(default=None, gt=0),
    before: Union[int, None] = Query(default=None, gt=0),
    page: Union[int, None] = Query(default=None, ge=0),
    size: Union[int, None] = 100,
    sort: Union[str, None] = Query(
        default=None, pattern="(annotated_count|state):(desc|asc)"
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
        sample_name=sample_name,
        after=after,
        before=before,
        page=page,
        size=size,
        sorting=sort,
        current_user=current_user,
    )

    # response
    meta_data = MetaData(total=total, page=page, size=len(data))
    return OkRespWithMeta[List[PreAnnotationResponse]](meta_data=meta_data, data=data)


@router.get(
    "/{task_id}/pre_annotations/{pre_annotation_id}",
    response_model=OkResp[PreAnnotationResponse],
    status_code=status.HTTP_200_OK,
)
async def get(
    task_id: int,
    pre_annotation_id: int,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a pre annotation result.
    """

    # business logic
    data = await service.get(
        db=db,
        task_id=task_id,
        pre_annotation_id=pre_annotation_id,
        current_user=current_user,
    )

    # response
    return OkResp[PreAnnotationResponse](data=data)


@router.delete(
    "/{task_id}/pre_annotations",
    response_model=OkResp[CommonDataResp],
    status_code=status.HTTP_200_OK,
)
async def delete(
    cmd: DeletePreAnnotationCommand,
    authorization: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(db_module.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    delete a annotation.
    """

    # business logic
    data = await service.delete(
        db=db, pre_annotation_ids=cmd.pre_annotation_ids, current_user=current_user
    )

    # response
    return OkResp[CommonDataResp](data=data)
