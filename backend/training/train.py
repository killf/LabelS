"""使用本地图片与 YOLO 标注训练，模型和日志保存在任务目录。"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TextIO
from zoneinfo import ZoneInfo

import yaml

LOGGER = logging.getLogger("backend.training")


class Tee(io.TextIOBase):
    """将终端输出同时写入训练日志，保留框架的进度信息。"""

    def __init__(self, terminal: TextIO, logfile: TextIO) -> None:
        self.terminal = terminal
        self.logfile = logfile

    def write(self, text: str) -> int:
        self.terminal.write(text)
        self.logfile.write(text)
        self.logfile.flush()

        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.logfile.flush()


def _dataset_file(directory: Path, value: str) -> Path:
    """解析数据集内的相对文件名，拒绝路径越界和链接逃逸。"""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or any(char in value for char in ("\\", ":", "\x00", "\r", "\n"))
    ):
        raise ValueError(f"Invalid dataset-relative path: {value!r}")
    resolved = (directory / path).resolve()
    if not resolved.is_relative_to(directory.resolve()):
        raise ValueError(f"Invalid dataset-relative path: {value!r}")
    return resolved


def prepare_dataset(dataset: Path, destination: Path, snapshot: Path) -> Path:
    """复制本地训练快照并生成绝对路径清单，不改动任务的原始标注。"""
    # 1. 保存原始清单，禁用数据配置中的下载脚本。
    snapshot.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    original = _dataset_file(dataset, "data.yaml")
    data = yaml.safe_load(original.read_text(encoding="utf-8-sig"))
    shutil.copy2(original, snapshot / "data.yaml")
    data.pop("download", None)
    data["path"] = str(destination.resolve())

    # 2. 只维护训练、测试两份清单，逐张复制图片和标签以冻结本次输入。
    copied = set()
    backgrounds = 0
    for split in ("train", "test"):
        filename = data.get(split)
        if filename != f"{split}.txt":
            raise ValueError(f"data.yaml {split} must reference {split}.txt")
        listing = _dataset_file(dataset, filename)
        shutil.copy2(listing, snapshot / filename)
        images = []
        for value in listing.read_text(encoding="utf-8-sig").splitlines():
            value = value.strip()
            if not value:
                continue
            relative = PurePosixPath(value)
            if len(relative.parts) < 2 or relative.parts[0] != "images":
                raise ValueError(f"{filename} must reference files under images/")
            source = _dataset_file(dataset, value)
            target = _dataset_file(destination, value)
            if value not in copied:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                label = str(
                    PurePosixPath("labels", *relative.parts[1:]).with_suffix(".txt")
                )
                original_label = _dataset_file(dataset, label)
                if original_label.is_file():
                    target_label = _dataset_file(destination, label)
                    target_label.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original_label, target_label)
                else:
                    backgrounds += 1
                copied.add(value)
            images.append(str(target))
        if not images:
            raise ValueError(f"{filename} contains no images")
        (destination / filename).write_text(
            "".join(f"{image}\n" for image in images), encoding="utf-8"
        )

    # 3. 测试集同时用于每轮验证和最优权重选择，没有第三份评估数据。
    data["val"] = "test.txt"
    config = destination / "data.yaml"
    config.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    LOGGER.info("Prepared %s local images, %s backgrounds", len(copied), backgrounds)
    return config


def _next_run_id(dataset: Path) -> str:
    """按现有模型和运行目录生成日期编号，不创建占号或锁。"""
    day = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    number = 0
    for directory in (dataset / "models", dataset / "runs"):
        for path in directory.glob(f"{day}-*"):
            match = re.match(rf"{day}-(\d+)(?:-|\.|$)", path.name)
            if match:
                number = max(number, int(match[1]))
    return f"{day}-{number + 1}"


def error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def run_training(
    dataset: Path,
    parameters: dict[str, object],
    work_dir: Path | None = None,
    result_file: Path | None = None,
) -> int:
    """冻结本地输入并训练，将最佳权重复制到任务 models/，日志留在 runs/。"""
    dataset = dataset.resolve()
    run_id = _next_run_id(dataset)
    if work_dir is None:
        parent = dataset / "runs"
        parent.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=parent))
    else:
        run_dir = work_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)

    # 1. 独立进程内同时记录控制台和训练日志，便于页面查看。
    with (
        (run_dir / "train.log").open("w", encoding="utf-8", buffering=1) as logfile,
        Tee(sys.stdout, logfile) as stdout,
        Tee(sys.stderr, logfile) as stderr,
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        try:
            LOGGER.info("Run %s, local dataset %s", run_id, dataset)
            data = prepare_dataset(dataset, run_dir / "dataset", run_dir / "input")
            train_args = parameters.copy()

            # 2. 复用当前 Python 的 GPU 后端，测试集验证结果决定 best.pt。
            import torch
            from ultralytics import YOLO

            if "device" not in train_args:
                train_args["device"] = (
                    "0"
                    if torch.cuda.is_available()
                    else "mps" if torch.backends.mps.is_available() else "cpu"
                )
            LOGGER.info(
                "Training device: %s, parameters: %s", train_args["device"], train_args
            )
            model = YOLO(train_args.pop("model"))
            model.train(
                data=str(data), project=str(run_dir), name="training", **train_args
            )

            # 3. 只发布最佳权重，其他训练文件保留在本次工作目录。
            best = Path(model.trainer.best)
            models = dataset / "models"
            models.mkdir(parents=True, exist_ok=True)
            published = models / f"{run_id}.pt"
            shutil.copy2(best, published)
            LOGGER.info("Saved model: %s", published)
            if result_file is not None:
                result_file.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "model_name": published.name,
                            "model_path": str(published),
                            "metrics": {
                                key: float(value)
                                for key, value in model.trainer.metrics.items()
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            return 0
        except (Exception, KeyboardInterrupt) as exc:
            LOGGER.error("Run %s failed: %s", run_id, error_text(exc))
            return 1
        finally:
            LOGGER.removeHandler(handler)


def terminate(signum: int, frame: object) -> None:
    raise KeyboardInterrupt(f"Received signal {signum}")


def main() -> int:
    """解析命令行参数，启动一次离线训练。"""
    # 1. 解析工作目录、训练参数和数据增强参数。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="本地任务目录，内含 data.yaml、train.txt、test.txt、images/ 和 labels/",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="训练快照、权重和日志的本地保存目录，默认任务目录下的 runs/<编号>/",
    )
    parser.add_argument(
        "--result-file",
        type=Path,
        help="将训练编号、模型地址和指标写入 JSON，供页面训练记录读取",
    )

    # 模型、训练规模和计算设备。
    parser.add_argument(
        "--model", default="yolo26s.pt", help="初始权重名称或本地路径，默认 yolo26s.pt"
    )
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数，默认 100")
    parser.add_argument(
        "--imgsz", type=int, default=1024, help="训练输入目标尺寸，单位像素，默认 1024"
    )
    parser.add_argument(
        "--batch", type=int, default=-1, help="每批图片数；-1 使用 YOLO 自动 batch"
    )
    parser.add_argument(
        "--device", help="计算设备，如 0、0,1、mps、cpu；不传则选择 PyTorch 可用后端"
    )
    parser.add_argument(
        "--workers", type=int, help="数据加载进程数，未指定时使用 YOLO 默认值"
    )

    # 优化、随机性与训练输出。
    parser.add_argument(
        "--optimizer", help="优化器名称，如 SGD、AdamW、auto，默认由 YOLO 决定"
    )
    parser.add_argument(
        "--seed", type=int, help="随机种子，用于复现实验，默认由 YOLO 决定"
    )
    parser.add_argument(
        "--amp", action=argparse.BooleanOptionalAction, help="启用或关闭混合精度训练"
    )
    parser.add_argument(
        "--plots",
        action=argparse.BooleanOptionalAction,
        help="生成或关闭训练和评估图表",
    )

    # 输入尺寸、几何变化和颜色增强；概率或幅度沿用 YOLO 的参数含义。
    parser.add_argument(
        "--rect",
        action=argparse.BooleanOptionalAction,
        help="按宽高比分组，减少训练补边",
    )
    parser.add_argument(
        "--multi-scale",
        type=float,
        help="输入尺寸随机变化比例，如 0.25 表示正负百分之 25",
    )
    parser.add_argument(
        "--close-mosaic", type=int, help="训练结束前关闭 Mosaic 增强的轮数"
    )
    parser.add_argument("--hsv-h", type=float, help="色相随机扰动幅度")
    parser.add_argument("--hsv-s", type=float, help="饱和度随机扰动幅度")
    parser.add_argument("--hsv-v", type=float, help="亮度随机扰动幅度")
    parser.add_argument("--translate", type=float, help="水平和垂直随机平移的最大比例")
    parser.add_argument(
        "--scale", type=float, help="随机缩放幅度，如 0.5 表示约 0.5 至 1.5 倍"
    )
    parser.add_argument("--fliplr", type=float, help="水平翻转概率，取值 0 至 1")
    parser.add_argument("--flipud", type=float, help="垂直翻转概率，取值 0 至 1")
    parser.add_argument("--degrees", type=float, help="随机旋转的最大角度，单位度")
    parser.add_argument(
        "--mosaic", type=float, help="使用四图拼接增强的概率，取值 0 至 1"
    )
    parser.add_argument(
        "--mixup", type=float, help="混合两张图片及其标注的概率，取值 0 至 1"
    )

    args = parser.parse_args()

    # 2. 分离工作目录，未设置的可选参数不传给 YOLO。
    parameters = vars(args).copy()
    dataset = parameters.pop("data").resolve()
    work_dir = parameters.pop("work_dir")
    result_file = parameters.pop("result_file")
    parameters = {key: value for key, value in parameters.items() if value is not None}

    # 3. 训练入口不安装依赖，不修改既有 PyTorch 运行时。
    previous = signal.signal(signal.SIGTERM, terminate)
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault(
        "YOLO_CONFIG_DIR",
        str((work_dir or dataset / "runs").resolve() / ".ultralytics"),
    )
    try:
        return run_training(dataset, parameters, work_dir, result_file)
    except (Exception, KeyboardInterrupt) as exc:
        print(error_text(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
