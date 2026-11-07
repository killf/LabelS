from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    SCHEME: str = "http"
    HOST: str = "localhost"
    PORT: str = "8000"
    API_V1_STR: str = "/api/v1"
    MEDIA_HOST: str = f"{SCHEME}://{HOST}:{PORT}"

    # SQLite 的持久化目录；媒体文件统一保存在 S3 中。
    BASE_DATA_DIR: str = "data"
    UPLOAD_DIR: str = "upload"
    UPLOAD_FILE_MAX_SIZE: int = 200_000_000  # ~200MB
    THUMBNAIL_HEIGH_PIXEL: int = 120
    S3_ENDPOINT: str = ""
    S3_REGION: str = ""
    S3_BUCKET: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PRESIGN_EXPIRE_SECONDS: int = 3600
    S3_PATH_STYLE: bool = False
    S3_USE_SSL: bool = True

    # Allow user-configured data-source S3 endpoints to point at private
    # networks (RFC1918 / ULA / loopback). Enabled by default for on-prem
    # deployments that use an internal MinIO/S3-compatible store. Even when
    # enabled, link-local (cloud metadata 169.254.0.0/16), multicast,
    # reserved and unspecified addresses are always rejected. Set to false to
    # restrict data-source endpoints to public hosts only (strict SSRF mode).
    ALLOW_PRIVATE_S3_ENDPOINT: bool = True

    AI_AUTO_LABEL_ENABLED: bool = True
    AI_DEVICE: str = ""  # 留空由 PyTorch 选择设备，验证时可显式指定 cpu。

    # 保留历史 SQLite 文件名，改名后继续读取已有数据库。
    DATABASE_URL: str = Field(
        default=f"sqlite:///{BASE_DATA_DIR}/labelu.sqlite",
        description="Database connection URL. Supports SQLite and MySQL.",
    )

    PASSWORD_SECRET_KEY: str = Field(
        default="",
        description="JWT secret key. Generate with: openssl rand -hex 32. MUST be set in production.",
    )

    TOKEN_GENERATE_ALGORITHM: str = "HS256"
    TOKEN_ACCESS_EXPIRE_MINUTES: int = 30
    # Sliding refresh: when an authenticated request arrives with a token whose
    # remaining lifetime is below this many minutes, a freshly issued token is
    # returned via the `X-New-Token` response header so active users never get
    # logged out. Should be smaller than TOKEN_ACCESS_EXPIRE_MINUTES.
    TOKEN_REFRESH_THRESHOLD_MINUTES: int = 15
    TOKEN_TYPE: str = "Bearer"
    EXPOSE_INTERNAL_ERRORS: bool = False


settings = Settings()
logger.info("Database directory: {}", settings.BASE_DATA_DIR)
