# LabelS 本地训练

入口为 `labels-train` 或 `python -m backend.training.train`。从本地项目目录读取 YOLO 数据，模型、指标与日志都保存在本地；不使用对象存储或云凭据。

## 输入与输出

```text
projects/1/
├── images/
├── labels/
├── train.txt
├── test.txt
├── data.yaml
├── models/<日期-编号>.pt
└── runs/<执行目录>/
    ├── train.log
    ├── input/       # 原始 YAML 和清单
    ├── dataset/     # 本次冻结的图片和标签
    └── training/    # YOLO 指标、图表和中间权重
```

数据清单必须非空，每行是 `images/` 内的相对图片路径。标签位于对应的 `labels/`，每行格式为 `class_id x_center y_center width height`，坐标归一化到 `[0, 1]`。无标签文件的图片按背景处理。输入路径拒绝越界和符号链接逃逸，数据配置中的下载脚本不执行。

```yaml
path: .
train: train.txt
val: test.txt
test: test.txt
names:
  - person
```

测试集同时用于每轮验证和选取 `best.pt`，不维护评估集或第三份清单，指标不是独立测试成绩。

## 运行

页面训练复用后端的 Python 环境，不能用轻量 Web 环境替换已有 AMD PyTorch。当前训练依赖固定 Ultralytics 8.4.203，并要求 PyTorch 2.9 至 3.0 之前的版本。已有 AMD ROCm 环境应直接复用，不重新安装另一套 PyTorch。

从仓库根目录运行：

```powershell
C:/Python314/python.exe -m backend.training.train `
  --data C:/Users/killf/github/LabelS/backend/data/projects/1 `
  --model yolo26n.pt --epochs 100 --imgsz 1024 --batch 2 --workers 0 --device 0
```

`--data` 是必填的本地项目目录。`--work-dir` 可指定运行目录，默认在该项目的 `runs/` 中创建独立目录。`--result-file` 可输出模型名称和指标 JSON，供页面训练记录读取。

默认模型是 `yolo26s.pt`；官方权重首次使用时由 Ultralytics 下载，也可通过 `--model` 提供本地权重路径。未指定设备时优先使用 CUDA/ROCm，再选择 MPS，最后选择 CPU。AMP 和增强参数沿用 YOLO 默认值，可通过 `--no-amp` 等命令行参数显式调整。

所有 argparse 参数独立声明，完整说明使用 `--help` 查看。输入快照不影响原始图片和人工标注，最优权重复制到本项目 `models/`，训练失败返回非零码并保留日志。

页面 JSON 参数通过 `--extra-params '{"lr0": 0.001, "amp": false}'` 传入离线入口。只接受 JSON 对象，按当前 Ultralytics 校验未知参数、类型和范围；基础表单、模型、设备和项目路径不可覆盖。与其他命令行参数重复时返回错误，训练不会启动。

## 页面记录与清理

项目页设置初始权重、轮数、输入尺寸和 batch，然后发起后台训练。记录保存参数、状态、指标、产出模型与执行时间，日志位于 `projects/<项目ID>/runs/<记录ID>/`。

“清理日志”只删除运行目录及中间文件，记录和产出模型保留。“清理记录”连同产出模型和日志一起删除；运行中或仍被使用的模型不能清理。单纯下载模型不会修改记录和文件。

## 共用服务镜像

```bash
# 从仓库根目录构建，同一镜像支持 Web 服务和离线训练。
docker build -t labels:local .

docker run --rm --gpus all --shm-size=8g --entrypoint labels-train \
  -v /your/local/project:/workspace/project \
  labels:local --data /workspace/project --epochs 100 --batch 2
```

容器必须挂载完整项目目录以保留输入、模型和日志。基础镜像复用已安装的 PyTorch/Ultralytics，不在运行时安装依赖。
