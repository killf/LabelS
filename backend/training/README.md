# YOLO MCP 本地训练

入口为 `yolo-mcp-train` 或 `python -m backend.training.train`。页面训练从数据库标注生成本次数据集；离线命令读取已准备好的 YOLO 数据目录。模型、指标与日志都保存在本地。

## 项目目录

```text
projects/1/
├── images/                     # 上传原图与缩略图
├── models/<日期-编号>.pt
└── runs/<记录 ID>/
    ├── dataset/
    │   ├── images/             # 本次训练使用的独立图片副本
    │   ├── labels/             # 按本次类别顺序生成的 YOLO 标签
    │   ├── train.txt
    │   ├── test.txt
    │   └── data.yaml
    ├── console.log
    ├── train.log
    └── training/               # 指标、图表和中间权重
```

项目只保存原始图片和数据库标注，不在标注保存时写训练副本。提交训练请求时才按当前已完成样本、数据划分和类别顺序生成快照；快照准备失败会回滚记录并清理本次目录。后台进程直接使用该快照，不重新读取项目标注。

原图不会被旋转或覆盖，旋转只作用于 run 内的图片副本。后续编辑、改类别、重新划分或删除原始样本，都不会改变已经生成的快照。新项目不创建 `uploads/`，旧附件按数据库中的路径继续读取，不自动搬迁。

## 数据格式

训练和测试清单必须非空，每行使用相对于清单的路径，例如 `./images/1.png`。标签位于对应的 `labels/`，每行格式为 `class_id x_center y_center width height`，坐标归一化到 `[0, 1]`。背景样本使用空标签文件。

```yaml
path: /absolute/path/to/run/dataset
train: train.txt
val: test.txt
test: test.txt
names:
  - person
```

测试集同时用于每轮验证和选取 `best.pt`，指标不是独立测试成绩。输入路径拒绝越界和符号链接逃逸，数据配置中的下载脚本不执行。

## 离线运行

页面训练复用后端的 Python 环境。当前使用 Ultralytics 8.4.203 和 PyTorch `>=2.9,<3`；已有 CUDA/AMD ROCm 环境应保留其 GPU 运行时。

从仓库根目录运行，下面的示例读取一个已有快照，在新的运行目录中训练：

```bash
python -m backend.training.train \
  --data "$HOME/.yolo-mcp/projects/1/runs/1/dataset" \
  --work-dir "$HOME/.yolo-mcp/projects/1/runs/manual-1" \
  --models-dir "$HOME/.yolo-mcp/projects/1/models" \
  --model yolo26n.pt --epochs 100 --imgsz 1024 --batch 2 --workers 0 --device 0
```

- `--data`：必填，包含图片、标签及三个配置文件的 YOLO 数据目录。
- `--work-dir`：训练运行目录，默认在 `--data` 下的 `runs/` 中创建独立目录。
- `--models-dir`：产出模型目录，默认是 `--data` 下的 `models/`；页面训练使用项目 `models/`。
- `--result-file`：将训练编号、模型路径和指标写入 JSON，供训练记录读取。

读取外部数据时，离线命令会复制数据到本次 `dataset/`，并在 `input/` 保留输入配置；如果输入已经是本次运行的 `dataset/`，则原地校验，不重复复制或创建 `input/`。

默认模型是 `yolo26s.pt`，官方权重首次使用时可能下载；也可提供本地权重路径。未指定设备时优先使用 CUDA/ROCm，再选择 MPS，最后选择 CPU。完整参数说明使用 `--help` 查看。

页面 JSON 参数通过 `--extra-params '{"lr0": 0.001, "amp": false}'` 传入。只接受 JSON 对象，参数由当前 Ultralytics 校验；基础表单、模型、设备及路径不能重复覆盖。训练失败返回非零码并保留日志。

## 训练记录

记录保存参数、状态、指标、产出模型与执行时间。最优权重发布到项目 `models/`，输入和中间权重保留在本次运行目录。

“清理日志”删除整个运行目录，包括该次数据快照、日志和中间文件，保留记录与产出模型。“删除”同时移除记录、产出模型和运行目录；运行中或仍在使用的模型不能删除。

## 共用服务镜像

```bash
docker build -t yolo-mcp:local .

docker run --rm --gpus all --shm-size=8g --entrypoint yolo-mcp-train \
  -v /your/local/project:/workspace/project \
  yolo-mcp:local --data /workspace/project/runs/1/dataset \
  --work-dir /workspace/project/runs/manual-1 --models-dir /workspace/project/models \
  --epochs 100 --batch 2
```

挂载完整项目目录以保留图片、模型和日志。镜像使用 `ultralytics/ultralytics` 基础环境，不在运行时安装依赖。
