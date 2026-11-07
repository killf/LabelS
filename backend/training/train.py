"""Download a standard YOLO dataset, train, and publish dataset-scoped artifacts."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import shutil
import signal
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TextIO

import yaml
from botocore.exceptions import BotoCoreError, ClientError

from .storage import S3Storage, relative_path

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


def prepare_dataset(store: S3Storage, root: Path, snapshot: Path) -> tuple[Path, bool]:
    """准备本地 YOLO 数据集，返回配置路径和是否存在测试样本。"""
    # 1. 下载数据集配置，先保存原始快照，再适配本地运行路径。
    snapshot.mkdir(parents=True, exist_ok=True)
    data_path = root / "data.yaml"
    store.download("data.yaml", data_path)
    shutil.copy2(data_path, snapshot / "data.yaml")

    data = yaml.safe_load(data_path.read_text(encoding="utf-8-sig"))
    # 样本由本入口下载，不执行数据配置中的 download 脚本。
    data.pop("download", None)
    data["path"] = str(root.resolve())

    # 2. 下载各划分清单，保留原始内容，并收集去重后的图片路径。
    samples: set[str] = set()
    has_test = False
    for split in ("train", "val", "test"):
        filename = data.get(split)
        if split == "test" and not filename:
            continue
        if filename != f"{split}.txt":
            raise ValueError(f"data.yaml {split} must reference {split}.txt")

        listing = root / filename
        store.download(filename, listing)
        shutil.copy2(listing, snapshot / filename)

        images = []
        for line in listing.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            image = relative_path(line.strip())
            if image.parts[0] != "images" or len(image.parts) < 2:
                raise ValueError(f"{filename} must reference files under images/")
            samples.add(image.as_posix())
            images.append(str(root.joinpath(*image.parts).resolve()))

        if not images and split != "test":
            raise ValueError(f"{filename} contains no images")
        if split == "test":
            has_test = bool(images)

        # 使用绝对路径，使 YOLO 读取清单时不依赖进程的工作目录。
        listing.write_text("".join(f"{image}\n" for image in images), encoding="utf-8")

    # 3. 按引用并行下载图片及对应标注，保留原有子目录关系。
    def download_sample(image_name: str) -> bool:
        """下载单个样本，返回是否缺少标注文件。"""
        image = relative_path(image_name)
        store.download(image_name, root.joinpath(*image.parts))

        label = Path("labels", *image.parts[1:]).with_suffix(".txt")
        return not store.download(label.as_posix(), root / label, optional=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        try:
            background_count = sum(pool.map(download_sample, sorted(samples)))
        except BaseException:
            # 首个失败或中断后取消排队任务，只等待已在传输的请求结束。
            pool.shutdown(cancel_futures=True)
            raise

    # 4. 保存本地配置并记录数据量，测试集是否可用交给训练流程处理。
    data_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    LOGGER.info(
        "Prepared %s images, %s without label files (background)",
        len(samples),
        background_count,
    )

    return data_path, has_test


def error_text(exc: BaseException) -> str:
    """记录 S3 错误码和请求编号，不打印可能携带签名的请求内容。"""
    if isinstance(exc, ClientError):
        code = exc.response["Error"]["Code"]
        request_id = exc.response.get("ResponseMetadata", {}).get("RequestId", "")
        return f"S3 code={code} request_id={request_id}"

    if isinstance(exc, BotoCoreError):
        return type(exc).__name__

    return f"{type(exc).__name__}: {exc}"


def run_training(
    store: S3Storage, parameters: dict[str, object], work_dir: Path
) -> int:
    """下载数据、训练与评估，再将权重和运行日志上传到数据集目录。"""
    # 1. 根据已有产物生成输出名称，创建本次本地目录，不写远端控制状态。
    run_id = store.next_run_id()
    run_parent = work_dir.resolve() / "runs"
    run_parent.mkdir(parents=True, exist_ok=True)

    # 不同数据集的远端编号可以相同，本地尾缀避免共享工作盘时撞目录。
    run_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=run_parent))

    # 2. 接管终端与框架输出，统一写入本次训练日志。
    exit_code = 0
    with (
        (run_dir / "train.log").open("w", encoding="utf-8", buffering=1) as logfile,
        Tee(sys.stdout, logfile) as stdout,
        Tee(sys.stderr, logfile) as stderr,
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s backend.training %(message)s")
        )
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)

        try:
            # 3. 准备本地数据，记录本次使用的训练参数。
            LOGGER.info("Run %s, dataset %s", run_id, store.uri)
            train_args = parameters.copy()
            LOGGER.info("Training parameters: %s", train_args)

            data_path, has_test = prepare_dataset(
                store, work_dir.resolve() / "datasets" / run_dir.name, run_dir / "input"
            )

            # 4. 选择可用设备，加载指定权重训练，由验证集选择最优权重。
            # 导入放在日志重定向之后，捕获框架训练日志和进度输出。
            import torch
            from ultralytics import YOLO

            # 未指定设备时，优先使用 CUDA/ROCm，其次 MPS，最后使用 CPU。
            if "device" not in train_args:
                if torch.cuda.is_available():
                    train_args["device"] = "0"
                elif torch.backends.mps.is_available():
                    train_args["device"] = "mps"
                else:
                    train_args["device"] = "cpu"

            LOGGER.info("Training device: %s", train_args["device"])
            model = YOLO(train_args.pop("model"))
            model.train(
                data=str(data_path), project=str(run_dir), name="training", **train_args
            )

            best = Path(model.trainer.best)

            # 5. train() 已加载最优权重，测试集只做最终评估，不参与选模。
            if has_test:
                model.val(
                    data=str(data_path),
                    split="test",
                    imgsz=train_args["imgsz"],
                    device=train_args["device"],
                    batch=model.trainer.batch_size,
                    project=str(run_dir),
                    name="test",
                    plots=train_args.get("plots", True),
                )

            # 6. 将选定权重平面发布到 models/，记录其可追溯地址。
            model_uri = store.upload_model(run_id, best)
            LOGGER.info("Published model: %s", model_uri)

        except (Exception, KeyboardInterrupt) as exc:
            # 失败只结束当前训练阶段，日志仍在 finally 中回传。
            LOGGER.error("Run %s failed: %s", run_id, error_text(exc))
            exit_code = 1

        finally:
            # 7. 无论训练成功或失败，先回传可用的日志和指标。
            try:
                store.upload_run(run_id, run_dir)
            except Exception as exc:
                LOGGER.error("Run log upload failed: %s", error_text(exc))
                exit_code = 1

            LOGGER.removeHandler(handler)

    return exit_code


def terminate(signum: int, frame: object) -> None:
    # 将 Pod 终止信号转为可捕获中断，使训练入口有机会回传日志。
    raise KeyboardInterrupt(f"Received signal {signum}")


def main() -> int:
    """解析命令行参数，启动一次离线训练。"""
    # 1. 解析工作目录、训练参数和数据增强参数。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/workspace"),
        help="下载数据、权重和训练日志的本地保存目录，默认 /workspace",
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
    work_dir = parameters.pop("work_dir")
    parameters = {key: value for key, value in parameters.items() if value is not None}

    # 3. 准备退出信号和框架环境，将运行配置保存在工作目录中。
    store = None
    previous = signal.signal(signal.SIGTERM, terminate)
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault(
        "YOLO_CONFIG_DIR", str(args.work_dir.resolve() / ".ultralytics")
    )

    # 4. 启动训练，退出时恢复信号处理并释放存储连接。
    try:
        store = S3Storage(os.environ["TRAIN_DATA_URI"])
        return run_training(store, parameters, work_dir)
    except (Exception, KeyboardInterrupt) as exc:
        print(error_text(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
