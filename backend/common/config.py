from loguru import logger
from pathlib import Path
from pydantic import Field, model_validator
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

    # SQLite 的持久化目录；图片、模型和训练日志均保存在该本地目录下。
    BASE_DATA_DIR: str = "data"
    UPLOAD_FILE_MAX_SIZE: int = 200_000_000  # ~200MB
    THUMBNAIL_HEIGH_PIXEL: int = 120

    AI_AUTO_LABEL_ENABLED: bool = True
    AI_DEVICE: str = ""  # 留空自动选择 CUDA/ROCm、MPS 或 CPU。

    # SQLite 默认与本地项目文件使用同一根目录。
    DATABASE_URL: str = Field(
        default="",
        description="Database connection URL. Supports SQLite and MySQL.",
    )

    PASSWORD_SECRET_KEY: str = Field(
        default="",
        description="JWT signing key. Generate with: openssl rand -hex 32.",
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

    @model_validator(mode="after")
    def default_database_directory(self) -> "Settings":
        """未指定数据库地址时，将 SQLite 放到配置后的本地数据根目录。"""
        if not self.DATABASE_URL:
            directory = Path(self.BASE_DATA_DIR).as_posix().rstrip("/")
            self.DATABASE_URL = f"sqlite:///{directory}/labels.sqlite"
        return self


settings = Settings()
logger.info("Database directory: {}", settings.BASE_DATA_DIR)
