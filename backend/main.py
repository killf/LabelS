from typing import Any, AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger
import click
import uvicorn
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from backend.adapter.routers import add_router
from backend.adapter.ws import add_ws_router
from backend.middleware import add_middleware
from backend.common.logger import init_logging
from backend.common.config import settings
from backend.common.error_code import add_exception_handler
from backend.migrations.run_migrate import run_db_migrations

from .version import version as labels_version

description = """
LabelS backend.

## Users

You will be able to:

* **Signup**
* **Login**
* **Logout**.

## Tasks

You will be able to:

* **CRUD**

## Task attachment

You will be able to:

* **upload attachment**
* **download attachment**
* **delete attachment**

## Task sample

You will be able to:

* **list sample**
* **create sample**
* **get sample**
* **update sample**
* **update dataset split**
"""


tags_metadata = [
    {
        "name": "users",
        "description": "Operations with users.",
    },
    {
        "name": "tasks",
        "description": "Task management.",
    },
    {
        "name": "attachments",
        "description": "Task attachment management.",
    },
    {
        "name": "samples",
        "description": "Task sample management.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时准备签名密钥、数据库，并标记上次中断的 AI 批次。"""
    if not settings.PASSWORD_SECRET_KEY:
        import secrets

        settings.PASSWORD_SECRET_KEY = secrets.token_hex(32)
        logger.warning(
            "PASSWORD_SECRET_KEY is unset; using a temporary key for this process."
        )

    init_logging()
    run_db_migrations()

    from backend.application.service.auto_label import fail_interrupted_jobs

    fail_interrupted_jobs()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="LabelS",
    description=description,
    version=labels_version,
    terms_of_service="",
    contact={
        "name": "LabelS",
        "url": "https://github.com/killf/LabelS",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=tags_metadata,
)

add_exception_handler(app=app)
add_router(app=app)
add_ws_router(app=app)
add_middleware(app=app)


class NoCacheStaticFiles(StaticFiles):
    """为 HTML 响应添加禁止缓存的头，其他静态资源沿用默认缓存行为。"""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        resp = super().file_response(*args, **kwargs)

        # No cache for html files
        if resp.media_type == "text/html":
            resp.headers.setdefault(
                "Cache-Control", "max-age=0, no-cache, no-store, must-revalidate"
            )
            resp.headers.setdefault("Pragma", "no-cache")
            resp.headers.setdefault("Expires", "0")

        return resp


app.mount("", NoCacheStaticFiles(packages=["backend"], html=True))


@click.command()
@click.option("--host", default="localhost", help="Server host")
@click.option("--port", default=8000, help="Server port")
@click.option("--media-host", default="http://localhost:8000", help="Media Host")
def cli(host: str, port: int, media_host: str):
    """按指定地址启动 LabelS HTTP 与 WebSocket 服务。"""
    settings.PORT = port
    settings.HOST = host
    settings.MEDIA_HOST = media_host

    uvicorn.run(app=app, host=settings.HOST, port=settings.PORT, ws="websockets")


if __name__ == "__main__":
    cli()
