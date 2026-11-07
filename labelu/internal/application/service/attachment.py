import re
import aiofiles
import os
import tempfile
from pathlib import Path, PurePosixPath

from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session

from labelu.internal.common.db import begin_transaction
from labelu.internal.common.config import settings
from labelu.internal.common.error_code import ErrorCode
from labelu.internal.common.error_code import LabelUException
from labelu.internal.common.storage import (
    build_thumbnail_key,
    create_thumbnail_bytes,
    get_storage_backend,
)
from labelu.internal.domain.models.user import User
from labelu.internal.domain.models.attachment import TaskAttachment
from labelu.internal.adapter.persistence import crud_task
from labelu.internal.adapter.persistence import crud_attachment
from labelu.internal.application.command.attachment import AttachmentCommand
from labelu.internal.application.command.attachment import AttachmentDeleteCommand
from labelu.internal.application.response.base import CommonDataResp
from labelu.internal.application.response.attachment import AttachmentResponse


def build_attachment_response(attachment) -> AttachmentResponse | None:
    if not attachment:
        return None

    # External data source attachment — use the data source's own credentials
    if getattr(attachment, "data_source_id", None) and getattr(
        attachment, "data_source", None
    ):
        from labelu.internal.application.service.datasource import get_presigned_url

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


async def create(
    db: Session, task_id: int, cmd: AttachmentCommand, current_user: User
) -> AttachmentResponse:
    storage = get_storage_backend()

    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task: {}", task_id)
        raise LabelUException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

        # file relative path
    path_filename = cmd.file.filename.split("/")
    #  filename = str(uuid.uuid4())[0:8] + "-" + path_filename[-1] NOTE: If you want keep filename safe, you can use uuid as filename
    filename = path_filename[-1]
    sanitized = re.sub(r"%", "_pct_", filename)
    sanitized = re.sub(r'[\\/*?:"<>|#]', "_", sanitized)
    # Sanitize the directory portion of the filename too: drop traversal
    # components ("..", ".", empty) and apply the same character sanitization,
    # so a crafted filename can never escape the task's upload directory.
    safe_parts = []
    for part in path_filename[:-1]:
        part = re.sub(r"%", "_pct_", part)
        part = re.sub(r'[\\/*?:"<>|#]', "_", part)
        if part in ("", ".", ".."):
            continue
        safe_parts.append(part)
    path = "/".join(safe_parts)
    # S3 对象键固定使用正斜杠，避免 Windows 路径分隔符写入对象名。
    attachment_relative_base_dir = PurePosixPath(settings.UPLOAD_DIR).joinpath(
        str(task_id), path
    )
    attachment_relative_path = str(attachment_relative_base_dir.joinpath(sanitized))

    # check file exist
    if storage.exists(attachment_relative_path):
        logger.error("file already exists:{}", attachment_relative_path)
        raise LabelUException(
            code=ErrorCode.CODE_51002_TASK_ATTACHMENT_ALREADY_EXISTS,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    CHUNK_SIZE = 8 * 1024 * 1024  # 8MB
    thumbnail_key = build_thumbnail_key(attachment_relative_path)
    thumbnail_bytes = None
    temp_file_path = None

    try:
        temp_file = tempfile.NamedTemporaryFile(
            suffix=Path(sanitized).suffix, delete=False
        )
        temp_file_path = Path(temp_file.name)
        temp_file.close()

        async with aiofiles.open(temp_file_path, "wb") as out_file:
            total_size = 0
            while True:
                chunk = await cmd.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                await out_file.write(chunk)
                total_size += len(chunk)
                logger.debug(f"{total_size} bytes written")

        if cmd.file.content_type and cmd.file.content_type.startswith("image/"):
            thumbnail_bytes = create_thumbnail_bytes(temp_file_path)

        storage.save_file(
            local_path=temp_file_path,
            key=attachment_relative_path,
            content_type=cmd.file.content_type,
        )

        if thumbnail_bytes:
            storage.save_bytes(
                content=thumbnail_bytes,
                key=thumbnail_key,
                content_type=cmd.file.content_type,
            )

        if temp_file_path and temp_file_path.exists():
            os.remove(temp_file_path)

        logger.info(f"File saved: {attachment_relative_path}, size: {total_size} bytes")
    except Exception as e:
        if temp_file_path and temp_file_path.exists():
            os.remove(temp_file_path)
        if storage.exists(attachment_relative_path):
            storage.delete(attachment_relative_path)
        if thumbnail_bytes and storage.exists(thumbnail_key):
            storage.delete(thumbnail_key)
        logger.error(f"Upload failed: {str(e)}")
        raise LabelUException(
            code=ErrorCode.CODE_51000_CREATE_ATTACHMENT_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # check file already saved
    if not storage.exists(attachment_relative_path) or (
        cmd.file.content_type
        and cmd.file.content_type.startswith("image/")
        and not storage.exists(thumbnail_key)
    ):
        logger.error(
            "cannot find saved images, path is:{}, image content-type is:{}, thumbnail path is:{}",
            attachment_relative_path,
            cmd.file.content_type,
            thumbnail_key,
        )
        raise LabelUException(
            code=ErrorCode.CODE_51000_CREATE_ATTACHMENT_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    attachment_url_path = attachment_relative_path.replace("\\", "/")
    # add a task file record
    with begin_transaction(db):
        attachment = crud_attachment.create(
            db=db,
            attachment=TaskAttachment(
                path=attachment_url_path,
                url="",
                filename=sanitized,
                created_by=current_user.id,
                updated_by=current_user.id,
                task_id=task_id,
            ),
        )

    # response
    url = storage.get_read_url(attachment_url_path)
    thumb_url = storage.get_read_url(thumbnail_key) if thumbnail_bytes else None
    return AttachmentResponse(
        id=attachment.id,
        url=url,
        thumbnail_url=thumb_url,
        stream_url=url,
        storage_backend=storage.backend_name,
        filename=sanitized,
    )


async def delete(
    db: Session, task_id: int, cmd: AttachmentDeleteCommand, current_user: User
) -> CommonDataResp:
    storage = get_storage_backend()

    # get task
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise LabelUException(
            code=ErrorCode.CODE_51001_TASK_ATTACHMENT_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if task.created_by != current_user.id:
        logger.error(
            "cannot delete attachment, the task owner is:{}, the delete operator is:{}",
            task.created_by,
            current_user.id,
        )
        raise LabelUException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # 外部数据源只移除引用，不删除源文件；全局 S3 删除失败时保留数据库记录。
    attachments = crud_attachment.get_by_ids(db=db, attachment_ids=cmd.attachment_ids)
    for attachment in attachments:
        if not attachment.data_source_id:
            storage.delete(attachment.path)
            thumbnail_key = build_thumbnail_key(attachment.path)
            if storage.exists(thumbnail_key):
                storage.delete(thumbnail_key)
    # delete
    with begin_transaction(db):
        crud_attachment.delete(db=db, attachment_ids=cmd.attachment_ids)

    # response
    return CommonDataResp(ok=True)
