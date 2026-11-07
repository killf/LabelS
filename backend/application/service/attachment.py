import re
import aiofiles
import tempfile
from pathlib import Path, PurePosixPath

from loguru import logger
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.application.service.access import assert_task_access
from backend.common.db import begin_transaction
from backend.common.config import settings
from backend.common.error_code import ErrorCode
from backend.common.error_code import LabelSException
from backend.common.storage import (
    build_thumbnail_key,
    create_thumbnail_bytes,
    get_storage_backend,
)
from backend.domain.models.user import User
from backend.domain.models.attachment import TaskAttachment
from backend.adapter.persistence import crud_task
from backend.adapter.persistence import crud_attachment
from backend.application.command.attachment import AttachmentCommand
from backend.application.command.attachment import AttachmentDeleteCommand
from backend.application.response.base import CommonDataResp
from backend.application.response.attachment import AttachmentResponse


def build_attachment_response(
    attachment: TaskAttachment | None,
) -> AttachmentResponse | None:
    """根据附件的数据源签发预览地址，空附件返回 None。"""
    if attachment is None:
        return None

    # External data source attachment — use the data source's own credentials
    if getattr(attachment, "data_source_id", None) and getattr(
        attachment, "data_source", None
    ):
        from backend.application.service.datasource import get_presigned_url

        url = get_presigned_url(attachment.data_source, attachment.path)
        return AttachmentResponse(
            id=attachment.id,
            filename=attachment.filename,
            url=url,
            thumbnail_url=None,
            stream_url=url,
            storage_backend="s3",
        )

    # 上传附件由全局 S3 保存，预览和视频流均使用对象签名地址。
    storage = get_storage_backend()
    url = storage.get_read_url(attachment.path)
    thumbnail_key = build_thumbnail_key(attachment.path)
    thumbnail_url = (
        storage.get_read_url(thumbnail_key) if storage.exists(thumbnail_key) else None
    )
    return AttachmentResponse(
        id=attachment.id,
        filename=attachment.filename,
        url=url,
        thumbnail_url=thumbnail_url,
        stream_url=url,
        storage_backend=storage.backend_name,
    )


def _upload_key(task_id: int, filename: str) -> str:
    """清理上传文件的相对路径，返回固定使用正斜杠的任务 S3 对象键。"""
    parts = [
        re.sub(r'[\\/*?:"<>|#]', "_", part.replace("%", "_pct_"))
        for part in filename.split("/")
    ]
    if parts[-1] in ("", ".", ".."):
        raise HTTPException(422, "上传文件必须提供有效文件名")
    directories = [part for part in parts[:-1] if part not in ("", ".", "..")]
    return str(
        PurePosixPath(settings.UPLOAD_DIR, str(task_id), *directories, parts[-1])
    )


async def create(
    db: Session, task_id: int, cmd: AttachmentCommand, current_user: User
) -> AttachmentResponse:
    """验证任务访问权，将上传文件和缩略图写入 S3，并保存附件记录。"""
    # 1. 先验证任务，再访问存储；对象键只来自清理后的相对路径。
    task = crud_task.get(db=db, task_id=task_id)
    if task is None:
        raise LabelSException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    assert_task_access(task, current_user)
    key = _upload_key(task_id, cmd.file.filename or "")
    storage = get_storage_backend()
    if storage.exists(key):
        raise LabelSException(
            code=ErrorCode.CODE_51002_TASK_ATTACHMENT_ALREADY_EXISTS,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    thumbnail_key = build_thumbnail_key(key)
    attempted_keys = []
    thumbnail_bytes = None
    try:
        # 2. 分块写入临时目录，离开上下文时统一清理本地文件。
        with tempfile.TemporaryDirectory(prefix="labels-upload-") as directory:
            local_path = Path(directory) / ("upload" + PurePosixPath(key).suffix)
            total_size = 0
            async with aiofiles.open(local_path, "wb") as output:
                while chunk := await cmd.file.read(8 * 1024 * 1024):
                    total_size += len(chunk)
                    if total_size > settings.UPLOAD_FILE_MAX_SIZE:
                        raise HTTPException(413, "上传文件超过允许的大小")
                    await output.write(chunk)

            if cmd.file.content_type and cmd.file.content_type.startswith("image/"):
                thumbnail_bytes = create_thumbnail_bytes(local_path)
            attempted_keys.append(key)
            storage.save_file(local_path, key, cmd.file.content_type)
            if thumbnail_bytes:
                attempted_keys.append(thumbnail_key)
                storage.save_bytes(
                    thumbnail_bytes, thumbnail_key, cmd.file.content_type
                )

        # 3. 存储写入成功后保存记录；数据库失败也清理本次对象。
        with begin_transaction(db):
            attachment = crud_attachment.create(
                db=db,
                attachment=TaskAttachment(
                    path=key,
                    url="",
                    filename=PurePosixPath(key).name,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                    task_id=task_id,
                ),
            )
    except Exception as error:
        for object_key in reversed(attempted_keys):
            try:
                storage.delete(object_key)
            except Exception as cleanup_error:
                logger.error(
                    "Upload cleanup failed: task_id={}, error={}",
                    task_id,
                    type(cleanup_error).__name__,
                )
        if isinstance(error, HTTPException):
            raise
        logger.error(
            "Upload failed: task_id={}, error={}", task_id, type(error).__name__
        )
        raise LabelSException(
            code=ErrorCode.CODE_51000_CREATE_ATTACHMENT_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from None

    # 4. 使用本次写入结果构造响应，不重复查询对象是否存在。
    logger.info("File saved: task_id={}, size={}", task_id, total_size)
    url = storage.get_read_url(key)
    return AttachmentResponse(
        id=attachment.id,
        filename=attachment.filename,
        url=url,
        stream_url=url,
        thumbnail_url=storage.get_read_url(thumbnail_key) if thumbnail_bytes else None,
        storage_backend=storage.backend_name,
    )


async def delete(
    db: Session, task_id: int, cmd: AttachmentDeleteCommand, current_user: User
) -> CommonDataResp:
    """由任务创建者删除附件；外部数据源仅删除引用，保留原对象。"""
    # 1. 验证任务创建者及待删除附件的归属。
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelSException(
            code=ErrorCode.CODE_51001_TASK_ATTACHMENT_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot delete attachment, the task owner is:{}, the delete operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 外部数据源只移除引用，不删除源文件；全局 S3 删除失败时保留数据库记录。
    attachments = crud_attachment.get_by_ids(db=db, attachment_ids=cmd.attachment_ids)
    if any(attachment.task_id != task_id for attachment in attachments):
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 2. 先清理自有对象，成功后再移除数据库引用。
    for attachment in attachments:
        if not attachment.data_source_id:
            storage = get_storage_backend()
            storage.delete(attachment.path)
            thumbnail_key = build_thumbnail_key(attachment.path)
            if storage.exists(thumbnail_key):
                storage.delete(thumbnail_key)
    # delete
    with begin_transaction(db):
        crud_attachment.delete(
            db=db, attachment_ids=[attachment.id for attachment in attachments]
        )

    # response
    return CommonDataResp(ok=True)
