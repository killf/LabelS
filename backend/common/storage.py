from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError
from PIL import Image

from backend.common.config import settings


class S3StorageBackend:
    """通过 S3 兼容接口保存附件和缩略图，并签发下载地址。"""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        if not settings.S3_BUCKET:
            raise ValueError("S3_BUCKET must be configured")

        self._bucket = settings.S3_BUCKET
        client_config = {}
        if settings.S3_REGION:
            client_config["region_name"] = settings.S3_REGION
        client_config["config"] = Config(
            s3={"addressing_style": "path" if settings.S3_PATH_STYLE else "auto"}
        )

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
            use_ssl=settings.S3_USE_SSL,
            **client_config,
        )

    @property
    def backend_name(self) -> str:
        return "s3"

    def save_file(
        self, local_path: Path, key: str, content_type: Optional[str] = None
    ) -> None:
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if extra_args:
            self._client.upload_file(
                str(local_path), self._bucket, key, ExtraArgs=extra_args
            )
        else:
            self._client.upload_file(str(local_path), self._bucket, key)

    def save_bytes(
        self, content: bytes, key: str, content_type: Optional[str] = None
    ) -> None:
        kwargs = {"Bucket": self._bucket, "Key": key, "Body": content}
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as error:
            # 只有对象不存在才返回 False；权限或连接错误交由调用方处理。
            if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def read_bytes(self, key: str) -> bytes:
        result = self._client.get_object(Bucket=self._bucket, Key=key)
        with result["Body"] as body:
            return body.read()

    def get_read_url(self, key: str, expires_in: Optional[int] = None) -> str:
        expires = expires_in or settings.S3_PRESIGN_EXPIRE_SECONDS
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )


def build_thumbnail_key(key: str) -> str:
    path = Path(key)
    return str(path.with_name(f"{path.stem}-thumbnail{path.suffix}")).replace("\\", "/")


def create_thumbnail_bytes(local_path: Path) -> bytes:
    """读取本地图片并返回缩略图字节，函数返回前关闭图片文件。"""
    with Image.open(local_path) as image:
        image.thumbnail(
            (
                round(image.width / image.height * settings.THUMBNAIL_HEIGH_PIXEL),
                settings.THUMBNAIL_HEIGH_PIXEL,
            ),
        )
        if image.mode != "RGB":
            image = image.convert("RGB")

        buffer = BytesIO()
        extension_to_format = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
        }
        format_name = extension_to_format.get(local_path.suffix.lower(), "PNG")
        image.save(buffer, format=format_name)
        return buffer.getvalue()


@lru_cache(maxsize=1)
def get_storage_backend() -> S3StorageBackend:
    return S3StorageBackend()
