"""通过 S3 兼容接口下载训练样本、上传模型及训练日志。"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def relative_path(value: str) -> PurePosixPath:
    """检查清单中的相对路径，避免下载文件时越出本地数据目录。"""
    path = PurePosixPath(value)

    if (
        not value
        or path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or any(char in value for char in ("\\", ":", "\x00", "\r", "\n"))
    ):
        raise ValueError(f"Invalid dataset-relative path: {value!r}")

    return path


class S3Storage:
    """从指定桶下载图片和标注，将权重写到 models/、训练日志写到 runs/。

    端点和凭据通过 S3_* 环境变量配置；不写入占号或任务控制记录。
    """

    def __init__(self, uri: str) -> None:
        # 1. 将数据集 URI 拆成桶名和对象前缀，tos:// 仅作为原有地址格式兼容。
        parsed = urlsplit(uri)
        if parsed.scheme not in {"s3", "tos"} or not parsed.netloc:
            raise ValueError("TRAIN_DATA_URI must be an s3:// or tos:// dataset directory")

        self.bucket = parsed.netloc
        prefix = parsed.path.strip("/")
        self.prefix = f"{relative_path(prefix).as_posix()}/" if prefix else ""
        self.scheme = parsed.scheme
        self.uri = f"{self.scheme}://{self.bucket}/{self.prefix}"

        # 2. 使用显式配置的 S3 兼容端点，不依赖某一家存储服务的专用 SDK。
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT"],
            region_name=os.environ.get("S3_REGION", "us-east-1"),
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            aws_session_token=os.environ.get("S3_SESSION_TOKEN") or None,
            config=Config(s3={"addressing_style": "path"}),
        )

    def download(self, relative: str, target: Path, *, optional: bool = False) -> bool:
        """下载一个图片、标注或配置文件；缺少可选标注时返回 False。"""
        key = self.prefix + relative_path(relative).as_posix()
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.client.download_file(self.bucket, key, str(target))
        except ClientError as exc:
            # 背景图片允许没有标注文件；鉴权失败和其他错误仍向上抛出。
            if optional and exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

        return True

    def next_run_id(self) -> str:
        """读取当日已有模型、日志的名称，返回 YYYYMMDD-N，不预写任何对象。"""
        # 1. 只读取当日模型文件和日志目录的名称，计算已使用的最大序号。
        day = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        number = 0
        paginator = self.client.get_paginator("list_objects_v2")

        for directory in ("models", "runs"):
            prefix = f"{self.prefix}{directory}/{day}-"
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                keys = [item["Key"] for item in page.get("Contents", [])]
                keys.extend(item["Prefix"] for item in page.get("CommonPrefixes", []))

                for key in keys:
                    match = re.fullmatch(r"(\d+)(?:/|\.pt)", key[len(prefix) :])
                    if match:
                        number = max(number, int(match[1]))

        # 2. 编号仅用于本次输出命名，不维护计数器、占用记录或冲突重试。
        return f"{day}-{number + 1}"

    def upload_model(self, run_id: str, source: Path) -> str:
        """把本次选出的 best.pt 上传为 models/<run-id>.pt。"""
        key = f"{self.prefix}models/{run_id}.pt"
        self.client.upload_file(str(source), self.bucket, key)

        return f"{self.scheme}://{self.bucket}/{key}"

    def upload_run(self, run_id: str, source: Path) -> None:
        """将本地运行目录中的日志、指标和配置快照上传到 runs/<run-id>/。"""
        # 1. 逐个上传日志产物；权重只保存在 models/，不重复上传。
        failed = []
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.suffix == ".pt":
                continue

            relative = path.relative_to(source).as_posix()
            try:
                self.client.upload_file(
                    str(path), self.bucket, f"{self.prefix}runs/{run_id}/{relative}"
                )
            except Exception as exc:
                failed.append(f"{relative}: {type(exc).__name__}")

        # 2. 上传失败不阻断其他日志回传，全部尝试后再报告缺失产物。
        if failed:
            raise RuntimeError("Incomplete run upload: " + ", ".join(failed))

    def close(self) -> None:
        self.client.close()
