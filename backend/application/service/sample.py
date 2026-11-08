import json
from typing import List, Tuple, Union

from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session

from backend.common.db import begin_transaction
from backend.common.error_code import ErrorCode
from backend.common.error_code import LabelSException
from backend.common.storage import (
    build_thumbnail_key,
    get_storage,
)
from backend.application.service.access import assert_project_access
from backend.adapter.persistence import (
    crud_attachment,
    crud_pre_annotation,
    crud_project,
)
from backend.adapter.persistence import crud_sample
from backend.domain.models.user import User
from backend.domain.models.project import Project
from backend.domain.models.project import ProjectStatus
from backend.domain.models.sample import ProjectSample
from backend.domain.models.sample import DatasetSplit, SampleState
from backend.application.command.sample import PatchSampleCommand
from backend.application.command.sample import CreateSampleCommand
from backend.application.response.base import UserResp
from backend.application.response.base import CommonDataResp
from backend.application.response.sample import CreateSampleResponse
from backend.application.response.sample import SampleResponse
from backend.application.service.dataset import sync_dataset
from backend.application.service.attachment import build_attachment_response
from backend.clients.ws import sampleConnectionManager
from backend.common.websocket import Message, MessageType
from backend.adapter.ws.sample import ProjectSampleWsPayload


def is_sample_pre_annotated(
    db: Session,
    project_id: int,
    sample_name: str | None = None,
    sample_id: int | None = None,
) -> bool:
    """检查样本的人工导入或 AI 预标注，AI 结果同时匹配样本 ID。"""
    if sample_name is None:
        return False

    annotations, _ = crud_pre_annotation.list_by(
        db=db,
        project_id=project_id,
        sample_name=sample_name,
        size=None,
    )
    for annotation in annotations:
        meta = json.loads(annotation.data).get("meta", {})
        if (
            meta.get("source_type") != "ai_generated"
            or meta.get("sample_id") == sample_id
        ):
            return True
    return False


async def create(
    db: Session, project_id: int, cmd: List[CreateSampleCommand], current_user: User
) -> CreateSampleResponse:
    obj_in = {}
    with begin_transaction(db):
        # check project exist
        project = crud_project.get(db=db, project_id=project_id, lock=True)
        if not project:
            logger.error("cannot find project:{}", project_id)
            raise LabelSException(
                code=ErrorCode.CODE_50002_PROJECT_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        assert_project_access(project, current_user)

        samples = [
            ProjectSample(
                inner_id=project.last_sample_inner_id + i + 1,
                project_id=project_id,
                file_id=sample.file_id,
                split=sample.split.value,
                created_by=current_user.id,
                updated_by=current_user.id,
                data=json.dumps(sample.data, ensure_ascii=False),
            )
            for i, sample in enumerate(cmd)
        ]
        obj_in[Project.last_sample_inner_id.key] = project.last_sample_inner_id + len(
            cmd
        )
        if project.status == ProjectStatus.DRAFT.value:
            obj_in[Project.status.key] = ProjectStatus.IMPORTED
        crud_project.update(db=db, db_obj=project, obj_in=obj_in)
        new_samples = crud_sample.batch(db=db, samples=samples)

    # response
    ids = [s.id for s in new_samples]
    return CreateSampleResponse(ids=ids)


def _sample_response(db: Session, sample: ProjectSample) -> SampleResponse:
    """从样本及关联用户构造统一响应，并签发附件预览地址。"""
    return SampleResponse(
        id=sample.id,
        split=sample.split,
        inner_id=sample.inner_id,
        state=sample.state,
        data=json.loads(sample.data),
        is_pre_annotated=is_sample_pre_annotated(
            db=db,
            project_id=sample.project_id,
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


async def list_by(
    db: Session,
    project_id: Union[int, None],
    after: Union[int, None],
    before: Union[int, None],
    page: Union[int, None],
    size: int,
    sorting: Union[str, None],
    current_user: User,
    split: DatasetSplit | None = None,
) -> Tuple[List[SampleResponse], int]:
    if project_id is not None:
        project = crud_project.get(db=db, project_id=project_id)
        if project is not None:
            assert_project_access(project, current_user)
    samples = crud_sample.list_by(
        db=db,
        project_id=project_id,
        after=after,
        before=before,
        page=page,
        size=size,
        sorting=sorting,
        split=split.value if split is not None else None,
    )

    total = crud_sample.count(
        db=db,
        project_id=project_id,
        split=split.value if split is not None else None,
    )

    # response
    return [_sample_response(db, sample) for sample in samples], total


async def get(
    db: Session, project_id: int, sample_id: int, current_user: User
) -> SampleResponse:
    sample = crud_sample.get(
        db=db,
        sample_id=sample_id,
    )

    if not sample or sample.project_id != project_id:
        logger.error("cannot find sample:{}", sample_id)
        raise LabelSException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    project = crud_project.get(db=db, project_id=sample.project_id)
    if project is not None:
        assert_project_access(project, current_user)

    # response
    return _sample_response(db, sample)


async def patch(
    db: Session,
    project_id: int,
    sample_id: int,
    cmd: PatchSampleCommand,
    current_user: User,
) -> SampleResponse:
    """保存样本标注或划分，同步 YOLO 数据集，成功后通知项目客户端。"""
    # 1. 验证项目访问权及样本归属。
    project = crud_project.get(db=db, project_id=project_id)
    if not project:
        logger.error("cannot find project:{}", project_id)
        raise LabelSException(
            code=ErrorCode.CODE_50002_PROJECT_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_project_access(project, current_user)

    # get sample
    sample = crud_sample.get(db=db, sample_id=sample_id)
    if not sample or sample.project_id != project_id:
        logger.error("cannot find sample:{}", sample_id)
        raise LabelSException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 2. 修改划分标签时保留现有标注；提交标注时更新其完成状态。
    sample_obj_in = {}
    if cmd.split is not None:
        sample_obj_in[ProjectSample.split.key] = cmd.split.value
    annotation_changed = bool(
        {"data", "state", "annotated_count"} & cmd.model_fields_set
    )
    if annotation_changed:
        if cmd.state == SampleState.SKIPPED.value:
            sample_obj_in[ProjectSample.state.key] = SampleState.SKIPPED.value
        else:
            sample_obj_in[ProjectSample.data.key] = json.dumps(
                cmd.data, ensure_ascii=False
            )
            sample_obj_in[ProjectSample.annotated_count.key] = cmd.annotated_count
            sample_obj_in[ProjectSample.state.key] = (
                SampleState.NEW.value
                if cmd.state == SampleState.NEW.value
                else SampleState.DONE.value
            )

    # 3. SQLite 保留可编辑标注，本地目录保存训练端直接使用的数据集。
    with begin_transaction(db):
        if annotation_changed and current_user not in sample.updaters:
            sample.updaters.append(current_user)
        updated_sample = crud_sample.update(db=db, db_obj=sample, obj_in=sample_obj_in)
        if annotation_changed:
            remaining = (
                db.query(ProjectSample)
                .filter(
                    ProjectSample.project_id == project_id,
                    ProjectSample.deleted_at.is_(None),
                    ProjectSample.state == SampleState.NEW.value,
                )
                .count()
            )
            crud_project.update(
                db=db,
                db_obj=project,
                obj_in={
                    Project.status.key: (
                        ProjectStatus.INPROGRESS.value
                        if remaining
                        else ProjectStatus.FINISHED.value
                    )
                },
            )

    sync_dataset(db, project, [updated_sample] if annotation_changed else [])

    # 4. 同步成功后通知其他客户端刷新。
    await sampleConnectionManager.send_message(
        client_id=f"project_{project_id}",
        message=Message(
            type=MessageType.UPDATE,
            data=ProjectSampleWsPayload(
                project_id=project_id,
                user_id=current_user.id,
                username=current_user.username,
                sample_id=sample_id,
            ),
        ),
    )

    # response
    return _sample_response(db, updated_sample)


async def delete(
    db: Session, sample_ids: List[int], current_user: User
) -> CommonDataResp:
    storage = get_storage()

    with begin_transaction(db):
        # delete media
        samples = crud_sample.get_by_ids(db=db, sample_ids=sample_ids)
        # authorize: caller must have access to every sample's project
        for project_id in {sample.project_id for sample in samples}:
            project = crud_project.get(db=db, project_id=project_id)
            if project is not None:
                assert_project_access(project, current_user)
        attachment_ids = [sample.file_id for sample in samples if sample.file_id]
        attachments = crud_attachment.get_by_ids(db=db, attachment_ids=attachment_ids)
        for attachment in attachments:
            storage.delete(attachment.path)
            thumbnail_key = build_thumbnail_key(attachment.path)
            if storage.exists(thumbnail_key):
                storage.delete(thumbnail_key)

        crud_sample.delete(db=db, sample_ids=sample_ids)

    for project_id in {sample.project_id for sample in samples}:
        project = crud_project.get(db=db, project_id=project_id)
        sync_dataset(
            db,
            project,
            [sample for sample in samples if sample.project_id == project_id],
        )

    # response
    return CommonDataResp(ok=True)
