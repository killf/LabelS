"""本地任务文件存储与短时图片访问地址。"""

from __future__ import annotations

import hashlib
import hmac
import shutil
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from PIL import Image

from backend.common.config import settings


class LocalStorage:
    """在 BASE_DATA_DIR 内读写任务文件，拒绝越界路径和符号链接逃逸。"""

    def __init__(self) -> None:
        self.root = Path(settings.BASE_DATA_DIR).resolve()

    def path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if (
            not key
            or relative.is_absolute()
            or ".." in relative.parts
            or any(character in key for character in ("\\", ":", "\x00"))
        ):
            raise ValueError("Invalid task-relative path")
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Path is outside the data directory")
        return target

    def save_file(self, local_path: Path, key: str) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)

    def save_bytes(self, content: bytes, key: str) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.path(key).read_text(encoding=encoding)

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def list_models(self, prefix: str) -> list[str]:
        directory = self.path(prefix)
        if not directory.is_dir():
            return []
        return sorted(
            (
                file.name
                for file in directory.glob("*.pt")
                if file.is_file() and file.resolve().is_relative_to(self.root)
            ),
            reverse=True,
        )

    def _signature(self, key: str, expires: int) -> str:
        value = f"{key}\n{expires}".encode("utf-8")
        return hmac.new(
            settings.PASSWORD_SECRET_KEY.encode("utf-8"), value, hashlib.sha256
        ).hexdigest()

    def get_read_url(self, key: str, expires_in: int = 3600) -> str:
        """图片只携带绑定当前文件的短时签名，不把登录令牌放入 URL。"""
        self.path(key)
        parts = PurePosixPath(key).parts
        if len(parts) < 4 or parts[0] != "tasks" or parts[2] != "uploads":
            raise ValueError("Only uploaded images may be previewed")
        expires = int(time.time()) + expires_in
        suffix = quote("/".join(parts[2:]), safe="/")
        signature = self._signature(key, expires)
        return (
            f"{settings.API_V1_STR}/tasks/{parts[1]}/files/{suffix}"
            f"?expires={expires}&signature={signature}"
        )

    def verify_read_url(self, key: str, expires: int, signature: str) -> bool:
        """验证文件路径、有效期和签名，签名不能用于其他文件。"""
        self.path(key)
        parts = PurePosixPath(key).parts
        return (
            len(parts) >= 4
            and parts[0] == "tasks"
            and parts[2] == "uploads"
            and int(time.time()) <= expires
            and hmac.compare_digest(self._signature(key, expires), signature)
        )


def build_thumbnail_key(key: str) -> str:
    path = PurePosixPath(key)
    return str(path.with_name(f"{path.stem}-thumbnail{path.suffix}"))


def create_thumbnail_bytes(local_path: Path) -> bytes:
    """读取本地图片并生成缩略图，返回前关闭全部图像资源。"""
    with Image.open(local_path) as source:
        source.thumbnail(
            (
                round(source.width / source.height * settings.THUMBNAIL_HEIGH_PIXEL),
                settings.THUMBNAIL_HEIGH_PIXEL,
            )
        )
        image = source.convert("RGB")
        try:
            buffer = BytesIO()
            formats = {
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".png": "PNG",
                ".webp": "WEBP",
                ".bmp": "BMP",
                ".tif": "TIFF",
                ".tiff": "TIFF",
            }
            image.save(buffer, format=formats[local_path.suffix.lower()])
            return buffer.getvalue()
        finally:
            image.close()


@lru_cache(maxsize=1)
def get_storage() -> LocalStorage:
    return LocalStorage()
