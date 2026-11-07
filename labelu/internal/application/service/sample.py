import json
from typing import List, Tuple, Union

from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session

from labelu.internal.common.db import begin_transaction
from labelu.internal.common.error_code import ErrorCode
from labelu.internal.common.error_code import LabelUException
from labelu.internal.common.storage import (
    build_thumbnail_key,
    get_storage_backend,
)
from labelu.internal.application.service.access import assert_task_access, assert_owner
from labelu.internal.adapter.persistence import (
    crud_attachment,
    crud_pre_annotation,
    crud_task,
)
from labelu.internal.adapter.persistence import crud_sample
from labelu.internal.adapter.persistence import crud_datasource
from labelu.internal.domain.models.user import User
from labelu.internal.domain.models.task import Task
from labelu.internal.domain.models.task import TaskStatus
from labelu.internal.domain.models.sample import TaskSample
from labelu.internal.domain.models.sample import SampleState
from labelu.internal.application.command.sample import PatchSampleCommand
from labelu.internal.application.command.sample import CreateSampleCommand
from labelu.internal.application.command.datasource import ImportS3SamplesCommand
from labelu.internal.application.response.base import UserResp
from labelu.internal.application.response.base import CommonDataResp
from labelu.internal.application.response.sample import CreateSampleResponse
from labelu.internal.application.response.sample import SampleResponse
from labelu.internal.application.service.dataset import sync_dataset
from labelu.internal.application.service.attachment import build_attachment_response
from labelu.internal.clients.ws import sampleConnectionManager
from labelu.internal.common.websocket import Message, MessageType
from labelu.internal.adapter.ws.sample import TaskSampleWsPayload


def is_sample_pre_annotated(
    db: Session, task_id: int, sample_name: str | None = None, sample_id: int | None = None
) -> bool:
    if sample_name is None:
        return False

    annotations, _ = crud_pre_annotation.list_by(
        db=db, task_id=task_id, sample_name=sample_name, size=None,
    )
    for annotation in annotations:
        meta = json.loads(annotation.data).get("meta", {})
        if meta.get("source_type") != "ai_generated" or meta.get("sample_id") == sample_id:
            return True
    return False



async def create(
    db: Session, task_id: int, cmd: List[CreateSampleCommand], current_user: User
) -> CreateSampleResponse:
    obj_in = {}
    with begin_transaction(db):
        # check task exist
        task = crud_task.get(db=db, task_id=task_id, lock=True)
        if not task:
            logger.error("cannot find task:{}", task_id)
            raise LabelUException(
                code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        assert_task_access(task, current_user)

        samples = [
            TaskSample(
                inner_id=task.last_sample_inner_id + i + 1,
                task_id=task_id,
                file_id=sample.file_id,
                split=sample.split.value,
                created_by=current_user.id,
                updated_by=current_user.id,
                data=json.dumps(sample.data, ensure_ascii=False),
            )
            for i, sample in enumerate(cmd)
        ]
        obj_in[Task.last_sample_inner_id.key] = task.last_sample_inner_id + len(cmd)
        if task.status == TaskStatus.DRAFT.value:
            obj_in[Task.status.key] = TaskStatus.IMPORTED
        crud_task.update(db=db, db_obj=task, obj_in=obj_in)
        new_samples = crud_sample.batch(db=db, samples=samples)

    # response
    ids = [s.id for s in new_samples]
    return CreateSampleResponse(ids=ids)


MAX_IMPORT_KEYS = 10000


def _collect_s3_keys(ds, prefix: str, extension: str | None) -> list[str]:
    """List all matching S3 object keys under *prefix*, paginating internally."""
    from labelu.internal.application.service.datasource import _build_s3_client

    client = _build_s3_client(ds)
    full_prefix = prefix if prefix else (ds.prefix or "")

    allowed_exts = None
    if extension:
        allowed_exts = {
            ("." + e.strip().lower().lstrip("."))
            for e in extension.split(",")
            if e.strip()
        }

    keys: list[str] = []
    continuation_token = None

    while True:
        kwargs = {"Bucket": ds.bucket, "Prefix": full_prefix, "MaxKeys": 1000}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        try:
            resp = client.list_objects_v2(**kwargs)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "S3 list_objects_v2 failed for datasource {}", ds.id
            )
            raise LabelUException(
                code=ErrorCode.CODE_62002_S3_REQUEST_FAILED,
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        for obj in resp.get("Contents", []):
            key: str = obj["Key"]
            if key.endswith("/"):
                continue
            if allowed_exts:
                ext = ("." + key.rsplit(".", 1)[-1].lower()) if "." in key else ""
                if ext not in allowed_exts:
                    continue
            keys.append(key)
            if len(keys) > MAX_IMPORT_KEYS:
                raise LabelUException(
                    code=ErrorCode.CODE_62000_S3_IMPORT_TOO_MANY,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        if not resp.get("IsTruncated"):
            break
        continuation_token = resp.get("NextContinuationToken")

    return keys


async def import_from_s3(
    db: Session,
    task_id: int,
    cmd: ImportS3SamplesCommand,
    current_user: User,
) -> CreateSampleResponse:
    """Import S3 objects as task samples (no file copy — stores reference only)."""
    from labelu.internal.domain.models.attachment import TaskAttachment

    with begin_transaction(db):
        task = crud_task.get(db=db, task_id=task_id, lock=True)
        if not task:
            raise LabelUException(
                code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        assert_task_access(task, current_user)

        ds = crud_datasource.get(db=db, ds_id=cmd.data_source_id)
        if not ds:
            raise LabelUException(
                code=ErrorCode.CODE_61000_NO_DATA,
                status_code=status.HTTP_404_NOT_FOUND,
            )
        assert_owner(ds, current_user)

        # Resolve object keys: either from explicit list or by listing S3 prefix
        object_keys = cmd.object_keys
        if not object_keys and cmd.prefix is not None:
            object_keys = _collect_s3_keys(ds, cmd.prefix, cmd.extension)

        if not object_keys:
            raise LabelUException(
                code=ErrorCode.CODE_62001_S3_IMPORT_NO_MATCH,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        attachments = []
        for key in object_keys:
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            att = TaskAttachment(
                path=key,
                url="",
                filename=filename,
                task_id=task_id,
                data_source_id=ds.id,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(att)
            attachments.append(att)
        db.flush()

        samples = [
            TaskSample(
                inner_id=task.last_sample_inner_id + i + 1,
                task_id=task_id,
                file_id=att.id,
                created_by=current_user.id,
                updated_by=current_user.id,
                data=json.dumps({}),
            )
            for i, att in enumerate(attachments)
        ]
        obj_in = {
            Task.last_sample_inner_id.key: task.last_sample_inner_id + len(samples)
        }
        if task.status == TaskStatus.DRAFT.value:
            obj_in[Task.status.key] = TaskStatus.IMPORTED
        crud_task.update(db=db, db_obj=task, obj_in=obj_in)
        new_samples = crud_sample.batch(db=db, samples=samples)

    return CreateSampleResponse(ids=[s.id for s in new_samples])


async def list_by(
    db: Session,
    task_id: Union[int, None],
    after: Union[int, None],
    before: Union[int, None],
    page: Union[int, None],
    size: int,
    sorting: Union[str, None],
    current_user: User,
) -> Tuple[List[SampleResponse], int]:
    if task_id is not None:
        task = crud_task.get(db=db, task_id=task_id)
        if task is not None:
            assert_task_access(task, current_user)
    samples = crud_sample.list_by(
        db=db,
        task_id=task_id,
        after=after,
        before=before,
        page=page,
        size=size,
        sorting=sorting,
    )

    total = crud_sample.count(db=db, task_id=task_id)

    # response
    return [
        SampleResponse(
            id=sample.id,
            split=sample.split,
            inner_id=sample.inner_id,
            state=sample.state,
            data=json.loads(sample.data),
            annotated_count=sample.annotated_count,
            is_pre_annotated=is_sample_pre_annotated(
                db=db,
                task_id=task_id,
                sample_id=sample.id,
                sample_name=sample.file.filename if sample.file else None,
            ),
            file=build_attachment_response(sample.file),
            created_at=sample.created_at,
            created_by=UserResp(
                id=sample.owner.id,
                username=sample.owner.username,
            ),
            updated_at=sample.updated_at,
            updaters=[
                UserResp(
                    id=updater.id,
                    username=updater.username,
                )
                for updater in sample.updaters
            ],
        )
        for sample in samples
    ], total


async def get(
    db: Session, task_id: int, sample_id: int, current_user: User
) -> SampleResponse:
    sample = crud_sample.get(
        db=db,
        sample_id=sample_id,
    )

    if not sample or sample.task_id != task_id:
        logger.error("cannot find sample:{}", sample_id)
        raise LabelUException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    task = crud_task.get(db=db, task_id=sample.task_id)
    if task is not None:
        assert_task_access(task, current_user)

    # response
    return SampleResponse(
        id=sample.id,
        split=sample.split,
        inner_id=sample.inner_id,
        state=sample.state,
        data=json.loads(sample.data),
        is_pre_annotated=is_sample_pre_annotated(
            db=db,
            task_id=task_id,
            sample_id=sample.id,
            sample_name=sample.file.filename if sample.file else None,
        ),
        file=build_attachment_response(sample.file),
        annotated_count=sample.annotated_count,
        created_at=sample.created_at,
        created_by=UserResp(
            id=sample.owner.id,
            username=sample.owner.username,
        ),
        updated_at=sample.updated_at,
        updaters=[
            UserResp(
                id=updater.id,
                username=updater.username,
            )
            for updater in sample.updaters
        ],
    )


async def patch(
    db: Session,
    task_id: int,
    sample_id: int,
    cmd: PatchSampleCommand,
    current_user: User,
) -> SampleResponse:

    # check task exist
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelUException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_task_access(task, current_user)

    # get sample
    sample = crud_sample.get(db=db, sample_id=sample_id)
    if not sample or sample.task_id != task_id:
        logger.error("cannot find sample:{}", sample_id)
        raise LabelUException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 1. 修改划分标签时保留现有标注；提交标注时更新其完成状态。
    sample_obj_in = {}
    if cmd.split is not None:
        sample_obj_in[TaskSample.split.key] = cmd.split.value
    annotation_changed = bool(
        {"data", "state", "annotated_count"} & cmd.model_fields_set
    )
    if annotation_changed:
        if cmd.state == SampleState.SKIPPED.value:
            sample_obj_in[TaskSample.state.key] = SampleState.SKIPPED.value
        else:
            sample_obj_in[TaskSample.data.key] = json.dumps(
                cmd.data, ensure_ascii=False
            )
            sample_obj_in[TaskSample.annotated_count.key] = cmd.annotated_count
            sample_obj_in[TaskSample.state.key] = (
                SampleState.NEW.value
                if cmd.state == SampleState.NEW.value
                else SampleState.DONE.value
            )

    # 2. SQLite 保留可编辑标注，S3 保存训练端直接使用的数据集。
    with begin_transaction(db):
        if annotation_changed and current_user not in sample.updaters:
            sample.updaters.append(current_user)
        updated_sample = crud_sample.update(db=db, db_obj=sample, obj_in=sample_obj_in)
        if annotation_changed:
            remaining = (
                db.query(TaskSample)
                .filter(
                    TaskSample.task_id == task_id,
                    TaskSample.deleted_at.is_(None),
                    TaskSample.state == SampleState.NEW.value,
                )
                .count()
            )
            crud_task.update(
                db=db,
                db_obj=task,
                obj_in={
                    Task.status.key: (
                        TaskStatus.INPROGRESS.value
                        if remaining
                        else TaskStatus.FINISHED.value
                    )
                },
            )

    sync_dataset(db, task, [updated_sample] if annotation_changed else [])

    # 3. 同步成功后通知其他客户端刷新。
    await sampleConnectionManager.send_message(
        client_id=f"task_{task_id}",
        message=Message(
            type=MessageType.UPDATE,
            data=TaskSampleWsPayload(
                task_id=task_id,
                user_id=current_user.id,
                username=current_user.username,
                sample_id=sample_id,
            ),
        ),
    )

    # response
    return SampleResponse(
        id=updated_sample.id,
        split=updated_sample.split,
        inner_id=updated_sample.inner_id,
        state=updated_sample.state,
        data=json.loads(updated_sample.data),
        is_pre_annotated=is_sample_pre_annotated(
            db=db,
            task_id=task_id,
            sample_id=sample.id,
            sample_name=sample.file.filename if sample.file else None,
        ),
        file=build_attachment_response(updated_sample.file),
        annotated_count=updated_sample.annotated_count,
        created_at=updated_sample.created_at,
        created_by=UserResp(
            id=updated_sample.owner.id,
            username=updated_sample.owner.username,
        ),
        updated_at=updated_sample.updated_at,
        updaters=[
            UserResp(
                id=updater.id,
                username=updater.username,
            )
            for updater in updated_sample.updaters
        ],
    )


async def delete(
    db: Session, sample_ids: List[int], current_user: User
) -> CommonDataResp:
    storage = get_storage_backend()

    with begin_transaction(db):
        # delete media
        samples = crud_sample.get_by_ids(db=db, sample_ids=sample_ids)
        # authorize: caller must have access to every sample's task
        for task_id in {sample.task_id for sample in samples}:
            task = crud_task.get(db=db, task_id=task_id)
            if task is not None:
                assert_task_access(task, current_user)
        attachment_ids = [sample.file_id for sample in samples if sample.file_id]
        attachments = crud_attachment.get_by_ids(db=db, attachment_ids=attachment_ids)
        for attachment in attachments:
            if attachment.data_source_id:
                continue
            storage.delete(attachment.path)
            thumbnail_key = build_thumbnail_key(attachment.path)
            if storage.exists(thumbnail_key):
                storage.delete(thumbnail_key)

        crud_sample.delete(db=db, sample_ids=sample_ids)

    for task_id in {sample.task_id for sample in samples}:
        task = crud_task.get(db=db, task_id=task_id)
        sync_dataset(
            db, task, [sample for sample in samples if sample.task_id == task_id]
        )

    # response
    return CommonDataResp(ok=True)
