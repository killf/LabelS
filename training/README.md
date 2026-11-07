# Ego Quality 离线训练

使用 YOLO26 官方预训练权重训练 Ego 视频质量检测模型。项目独立运行，不提供部署清单，不接入 CI 或自动 Review，单元测试可选。代码随 LabelS 维护，消费标注保存时同步的标准 YOLO 数据集。训练环境和镜像独立于 Web 应用。

## 数据与环境

`TRAIN_DATA_URI` 指向 TOS 数据集目录，例如：

```text
TRAIN_DATA_URI=tos://datafactory-model-resource-test/dataset/玩手机/
```

```text
dataset/玩手机/
├── raw/                         # 人工定期补充的未标注数据池
├── images/                      # 人工选出的图片
├── labels/                      # YOLO 标注，与图片相对路径一致
├── train.txt
├── val.txt
├── test.txt                     # 可选；也可为空，不用于选择 best.pt
├── data.yaml
├── models/
│   └── 20261107-1.pt             # 验证集选出的 best.pt，平面存放
└── runs/
    └── 20261107-1/              # 日志、指标、输入清单与配置快照
```

人工准备图片并完成标注、划分和同步后再启动训练。清单只收录已准备好的样本；训练端不重新划分数据。建议按源视频分组，避免相邻帧分散到不同集合。

`data.yaml` 示例（类别以实际标注为准）：

```yaml
path: .
train: train.txt
val: val.txt
test: test.txt
names:
  0: phone_use
```

各清单每行写一个相对数据集根目录的路径，例如 `./images/video-a/frame-001.jpg`，也接受 `images/video-a/frame-001.jpg`。对应标注为 `labels/video-a/frame-001.txt`，每行是 `class_id x_center y_center width height`，坐标归一化到 `[0, 1]`。标准 YOLO 的背景样本可以没有标注文件，S3 接口明确返回对象不存在时按背景处理并记录数量；权限、网络和其他下载错误会终止本次运行。

程序只下载 `data.yaml`、划分清单及引用的图片和标注，不扫描 `raw/`，不递归下载模型或历史运行结果。每次运行使用独立的本地数据目录。原始 YAML 与清单保存在运行快照中，本地训练副本适配为当前磁盘路径。

环境变量：

| 名称 | 用途 |
| --- | --- |
| `TRAIN_DATA_URI` | 必填，数据集根目录，支持 `s3://` 和原有 `tos://` 地址 |
| `S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY` | 必填，通过运行环境注入 |
| `S3_SESSION_TOKEN` | 可选，临时凭据令牌 |
| `S3_REGION` | 签名地域，默认 `us-east-1`；示例 TOS 桶配置为 `cn-beijing` |
| `S3_ENDPOINT` | 必填，S3 兼容接口地址；示例内网端点为 `https://tos-s3-cn-beijing.ivolces.com` |

示例文件为 `.env.example`。程序通过 boto3 调用 S3 兼容接口，不依赖 TOS 专用 SDK。凭据显式使用上述环境变量，不自动加载 `.env`。访问范围需要包含输入读取、当日 `runs/` 和 `models/` 前缀列举及产物写入。

## 训练配置

使用普通 `argparse` 命令行参数：默认官方 `yolo26s.pt`、`--imgsz 1024`、`--epochs 100`、`--batch -1`。未指定 `--device` 时依次选择可用的 CUDA/ROCm、Apple MPS、CPU，也可显式指定 `--device cpu` 或 `--device 0`。其他参数未传时沿用固定版本 YOLO 的默认值，包括 AMP 和在线检测增强。输入保留原图比例，补边到 1024×1024，不预先修改 TOS 图片。训练使用 `train.txt`，验证集选出 `best.pt`，训练结束后有非空测试清单时再评估测试集。

首次使用的官方权重由 Ultralytics 自动下载，Pod 需要访问官方发布源。不能访问时，提前准备官方权重到挂载磁盘，通过 `--model /workspace/weights/yolo26s.pt` 指定。项目的训练数据和训练输出不打包进镜像。PyTorch 版本由后端和依赖约束共同选择，GPU 由宿主驱动及容器运行时提供。

训练参数直接在每次启动时传入，无需修改文件或重新构建镜像。支持 `--model`、`--epochs`、`--imgsz`、`--batch`、`--device`、`--workers`、`--optimizer`、`--seed`，以及增强参数如 `--mosaic`、`--scale`、`--hsv-v`。布尔参数使用 `--amp` / `--no-amp` 等形式，完整列表见 `--help`。依赖亮度或方向的质量类别，需要相应调整增强，避免改变标签含义。实际生效参数由框架写入训练输出的 `args.yaml`，并随日志上传。

## 本地启动

从本项目目录执行，使用与显卡运行时匹配的 Python：

```bash
uv venv
uv pip install -e .
# 先在当前 shell 注入上表中的环境变量。
uv run --no-sync ego-quality-train --work-dir ./workspace
```

传入本次训练参数：

```bash
uv run --no-sync ego-quality-train --work-dir ./workspace \
  --epochs 200 --batch 8 --imgsz 1024 --device 0 --workers 8
```

`pyproject.toml` 配置了 uv 原生的 `torch-backend = "auto"`。安装时 uv 根据驱动选择 PyTorch 后端，普通依赖继续使用阿里云镜像：

| 环境 | 安装与运行 |
| --- | --- |
| NVIDIA | 选择与驱动匹配的 CUDA wheel，训练使用 GPU |
| 支持 ROCm 的 AMD 环境 | 选择 ROCm wheel，训练沿用 PyTorch 的 CUDA 设备接口 |
| Apple Silicon（M1 等） | 使用官方 macOS ARM64 wheel，训练选择可用的 MPS |
| 无可识别的受支持 GPU 后端 | 安装 CPU wheel，训练使用 CPU |

AMD 支持范围取决于 GPU、操作系统和 ROCm 驱动组合。不使用 CPU 版 PyTorch 的后端可用性判断机器是否有 AMD 显卡。`--batch -1` 在 CPU/MPS 上由 YOLO 使用其默认 batch，也可自行指定 `--batch 1` 等正整数。

本机已有 Python 3.14、AMD Radeon 8060S，以及 `torch 2.13.0+rocm10.0.0`、对应 torchvision。它们安装在 Python 用户包目录，复用时把 uv 的目标目录指向该位置，避免安装另一套 PyTorch：

```powershell
uv pip install --python C:\Python314\python.exe `
  --target C:\Users\killf\AppData\Roaming\Python\Python314\site-packages -e .

C:\Python314\python.exe -m ego_quality.train --work-dir ./workspace --epochs 100
```

上述本机环境已通过包元数据和系统显卡信息核对，未执行 GPU 训练测试。Windows AMD 的官方 PyTorch 安装渠道与 Linux ROCm 索引不同，已有厂商运行时应优先复用，不能把 `uv` 的默认 CPU 包选择当作显卡识别结果。

按本轮约定，验证仅用本机 Python 和 CPU。明确限定 CPU 安装与运行时：

```bash
uv pip install -e . --torch-backend cpu
uv run --no-sync ego-quality-train --work-dir ./workspace --device cpu --batch 1
```

自动后端选择仅用于 `uv pip`，因此本项目不再使用 `uv.lock` 或 `uv sync`。运行时使用 `uv run --no-sync`，避免项目同步重新替换已选择的 PyTorch 后端。原理见 [uv 官方说明](https://docs.astral.sh/uv/guides/integration/pytorch/#automatic-backend-selection)；MPS 使用方式见 [PyTorch 官方说明](https://docs.pytorch.org/docs/stable/notes/mps.html)。

## 容器启动

基础镜像使用私有化的 `datafactory-cn-beijing.cr.volces.com/common/ultralytics`。项目直接安装到基座的 Python 环境，复用其中满足版本约束的 PyTorch，不另建一套 CUDA 虚拟环境。构建阶段关闭硬件自动探测，训练设备在容器启动后选择。

构建上下文仅为当前项目目录：

```bash
docker build -t ego-quality:local .
docker run --rm --gpus all --shm-size=8g \
  --env-file .env \
  -v /your/local/ego-quality-workspace:/workspace \
  ego-quality:local
```

复用同一镜像调整参数：

```bash
docker run --rm --gpus all --shm-size=8g \
  --env-file .env -v /your/local/ego-quality-workspace:/workspace \
  ego-quality:local --epochs 200 --batch 8 --imgsz 1024
```

已有 GPU Pod 使用相同镜像、环境变量和 `/workspace` 挂载执行即可，不提供 Kubernetes 清单。工作磁盘需容纳本批次图片、标注及训练输出；保留挂载目录便于训练或 TOS 上传失败后检查产物。

## 编号与结果

`run-id` 按北京时间日期和已有产物的最大序号加一生成，例如 `20261107-1`。只读取当天 `runs/`、`models/` 的名称，不预占编号、不维护计数器、不写运行控制记录，也没有锁和冲突重试。

成功后上传 `models/<run-id>.pt`；训练输出中的其他 `.pt` 留在本地，不重复上传到 `runs/`。日志、指标图表、输入和配置快照上传到 `runs/<run-id>/`。训练结果和异常直接写入日志，以进程退出码表示本次执行结果。

可捕获异常和 SIGTERM 会触发日志回传，上传不可用时保留本地产物并返回非零退出码。SIGKILL、断电和磁盘损坏不保证完成回传。模型地址写入日志；日志上传失败时即使模型已经发布，进程仍返回非零码。

迁移状态与验证范围见 [交接说明](../HANDOFF.md)。
