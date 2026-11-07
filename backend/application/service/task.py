import json
from typing import List, Tuple

from loguru import logger
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.common.db import begin_transaction
from backend.common.error_code import ErrorCode
from backend.common.error_code import LabelSException
from backend.domain.models.user import User
from backend.domain.models.task import Task
from backend.domain.models.attachment import TaskAttachment
from backend.common.storage import get_storage_backend, build_thumbnail_key
from backend.domain.models.task import TaskStatus
from backend.domain.models.sample import SampleState
from backend.application.service.access import assert_task_access
from backend.application.service.dataset import (
    assert_dataset_destination,
    dataset_classes,
    sync_dataset,
)
from backend.adapter.persistence import crud_task, crud_user
from backend.adapter.persistence import crud_sample
from backend.application.command.task import BasicConfigCommand
from backend.application.command.task import UpdateCommand
from backend.application.response.base import UserResp
from backend.application.response.user import UserResponse
from backend.application.response.base import CommonDataResp
from backend.application.response.task import TaskStatics
from backend.application.response.task import TaskResponse
from backend.application.response.task import TaskResponseWithStatics


async def create(
    db: Session, cmd: BasicConfigCommand, current_user: User
) -> TaskResponse:
    assert_dataset_destination(db, cmd.dataset_data_source_id, current_user)
    if cmd.media_type != "IMAGE":
        raise HTTPException(422, "YOLO 数据集任务使用图片标注")

    # 创建任务时固定本次使用的 S3 数据源与目录。

    with begin_transaction(db):
        new_task = crud_task.create(
            db=db,
            task=Task(
                status=TaskStatus.DRAFT.value,
                name=cmd.name,
                dataset_data_source_id=cmd.dataset_data_source_id,
                dataset_prefix=cmd.dataset_prefix.strip("/"),
                description=cmd.description,
                media_type=cmd.media_type,
                tips=cmd.tips,
                created_by=current_user.id,
                updated_by=current_user.id,
            ),
        )

    # response
    return TaskResponse(
        id=new_task.id,
        ai_model_name=new_task.ai_model_name,
        dataset_data_source_id=new_task.dataset_data_source_id,
        dataset_prefix=new_task.dataset_prefix,
        name=new_task.name,
        description=new_task.description,
        tips=new_task.tips,
        status=new_task.status,
        media_type=new_task.media_type,
        created_at=new_task.created_at,
        created_by=UserResp(
            id=new_task.owner.id,
            username=new_task.owner.username,
        ),
    )


async def list_by(
    db: Session,
    current_user: User,
    page: int,
    size: int,
) -> Tuple[List[TaskResponseWithStatics], int]:
    # get task list
    tasks, total_task = crud_task.list_by(
        db=db, owner_id=current_user.id, page=page, size=size
    )

    # get progress
    task_ids = [task.id for task in tasks]
    statics = crud_sample.statics(db=db, task_ids=task_ids)

    # response
    tasks_with_statics = [
        TaskResponseWithStatics(
            id=task.id,
            ai_model_name=task.ai_model_name,
            dataset_data_source_id=task.dataset_data_source_id,
            dataset_prefix=task.dataset_prefix,
            name=task.name,
            description=task.description,
            tips=task.tips,
            media_type=task.media_type,
            config=task.config,
            status=task.status,
            created_at=task.created_at,
            created_by=UserResp(
                id=task.owner.id,
                username=task.owner.username,
            ),
            stats=TaskStatics(
                new=statics.get(f"{task.id}_{SampleState.NEW.value}", 0),
                done=statics.get(f"{task.id}_{SampleState.DONE.value}", 0),
                skipped=statics.get(f"{task.id}_{SampleState.SKIPPED.value}", 0),
            ),
        )
        for task in tasks
    ]
    return tasks_with_statics, total_task


async def get(db: Session, task_id: int, current_user: User) -> TaskResponseWithStatics:

    # get task detail
    task = crud_task.get(db=db, task_id=task_id)

    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # not the collaborators
    if task.created_by != current_user.id and current_user not in task.collaborators:
        logger.error(
            "cannot get task, the task owner is:{}, the get operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # get progress
    statics = crud_sample.statics(
        db=db,
        task_ids=[task.id],
    )

    # response
    return TaskResponseWithStatics(
        id=task.id,
        ai_model_name=task.ai_model_name,
        dataset_data_source_id=task.dataset_data_source_id,
        dataset_prefix=task.dataset_prefix,
        name=task.name,
        description=task.description,
        tips=task.tips,
        media_type=task.media_type,
        config=task.config,
        status=task.status,
        created_at=task.created_at,
        created_by=UserResp(
            id=task.owner.id,
            username=task.owner.username,
        ),
        stats=TaskStatics(
            new=statics.get(f"{task.id}_{SampleState.NEW.value}", 0),
            done=statics.get(f"{task.id}_{SampleState.DONE.value}", 0),
            skipped=statics.get(f"{task.id}_{SampleState.SKIPPED.value}", 0),
        ),
    )


async def get_collaborators(db: Session, task_id: int, current_user: User):
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return [
        UserResponse(id=user.id, username=user.username) for user in task.collaborators
    ]


async def add_collaborator(db: Session, task_id: int, user_id: int, current_user: User):
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot add collaborator, the task owner is:{}, the add operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user = crud_user.get(db=db, id=user_id)
    if not user:
        logger.error("cannot find user:{}", user_id)
        raise LabelSException(
            code=ErrorCode.CODE_40002_USER_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # collaborator exists
    if user in task.collaborators:
        logger.error("collaborator already exists:{}", user_id)
        raise LabelSException(
            code=ErrorCode.CODE_50003_COLLABORATOR_ALREADY_EXISTS,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    with begin_transaction(db):
        task.collaborators.append(user)

    return UserResponse(id=user.id, username=user.username)


async def batch_add_collaborators(
    db: Session, task_id: int, user_ids: List[int], current_user: User
):
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot add collaborator, the task owner is:{}, the add operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user_ids = (
        set(user_ids)
        - set([user.id for user in task.collaborators])
        - set([task.created_by])
    )
    users = crud_user.list_by_ids(db=db, ids=user_ids)
    if len(users) != len(user_ids):
        logger.error("cannot find users:{}", user_ids)
        raise LabelSException(
            code=ErrorCode.CODE_40002_USER_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    with begin_transaction(db):
        task.collaborators.extend(users)

    return [UserResponse(id=user.id, username=user.username) for user in users]


async def remove_collaborator(
    db: Session, task_id: int, user_id: int, current_user: User
):
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot remove collaborator, the task owner is:{}, the remove operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user = crud_user.get(db=db, id=user_id)
    if not user:
        logger.error("cannot find user:{}", user_id)
        raise LabelSException(
            code=ErrorCode.CODE_40002_USER_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if user not in task.collaborators:
        logger.error("cannot find collaborator:{}", user_id)
        raise LabelSException(
            code=ErrorCode.CODE_50004_COLLABORATOR_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    with begin_transaction(db):
        task.collaborators.remove(user)

    return CommonDataResp(ok=True)


async def batch_remove_collaborators(
    db: Session, task_id: int, user_ids: List[int], current_user: User
):
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot remove collaborator, the task owner is:{}, the remove operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    users = crud_user.list_by_ids(db=db, ids=user_ids)
    if len(users) != len(user_ids):
        logger.error("cannot find users:{}", user_ids)
        raise LabelSException(
            code=ErrorCode.CODE_40002_USER_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    with begin_transaction(db):
        for user in users:
            if user in task.collaborators:
                task.collaborators.remove(user)

    return CommonDataResp(ok=True)


async def update(
    db: Session, task_id: int, cmd: UpdateCommand, current_user: User
) -> TaskResponse:

    # get task
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_task_access(task, current_user)

    # update
    obj_in = cmd.model_dump(exclude_unset=True)
    if cmd.dataset_data_source_id is not None:
        assert_dataset_destination(db, cmd.dataset_data_source_id, current_user)
    if cmd.config:
        dataset_classes(json.loads(cmd.config))
    if cmd.media_type and cmd.media_type != "IMAGE":
        raise HTTPException(422, "YOLO 数据集任务使用图片标注")
    if cmd.config:
        obj_in[Task.status.key] = TaskStatus.CONFIGURED
    with begin_transaction(db):
        updated_task = crud_task.update(db=db, db_obj=task, obj_in=obj_in)

    if {"config", "dataset_data_source_id", "dataset_prefix"} & cmd.model_fields_set:
        sync_dataset(db, updated_task)

    # response
    return TaskResponse(
        id=updated_task.id,
        ai_model_name=updated_task.ai_model_name,
        dataset_data_source_id=updated_task.dataset_data_source_id,
        dataset_prefix=updated_task.dataset_prefix,
        name=updated_task.name,
        description=updated_task.description,
        tips=updated_task.tips,
        media_type=updated_task.media_type,
        config=updated_task.config,
        status=updated_task.status,
        created_at=updated_task.created_at,
        created_by=UserResp(
            id=updated_task.owner.id,
            username=updated_task.owner.username,
        ),
    )


async def delete(db: Session, task_id: int, current_user: User) -> CommonDataResp:

    # get task
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot delete task, the task owner is:{}, the delete operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 删除任务上传的附件与缩略图；外部源文件和已同步的数据集保留。
    storage = get_storage_backend()
    attachments = (
        db.query(TaskAttachment)
        .filter(
            TaskAttachment.task_id == task_id,
            TaskAttachment.data_source_id.is_(None),
            TaskAttachment.deleted_at.is_(None),
        )
        .all()
    )
    for attachment in attachments:
        storage.delete(attachment.path)
        storage.delete(build_thumbnail_key(attachment.path))

    # delete
    with begin_transaction(db):
        crud_task.delete(db=db, db_obj=task)

    # response
    return CommonDataResp(ok=True)
