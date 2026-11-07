# LabelS 迁移交接

日期：2026-11-07。用户决定将标注工具和训练部分独立为公开仓库 `killf/LabelS`，本地目录为 `C:\Users\killf\github\LabelS`。本轮以迁移完成为止，后续工作在新会话继续。

## 已确认范围与实现

- 后端保留内部 `labelu` 包名，前端保留完整 LabelU-Kit 源码和依赖锁文件，许可证保留。
- 媒体文件只使用 S3 兼容存储；SQLite 保存任务、账户、原始标注和数据集划分。
- 每个任务选择已有 S3 数据源和相对目录，保存后直接同步标准 YOLO 数据集；已移除导出入口与导出任务代码。
- 样本划分为训练 `train`、测试 `test`、评估 `val`，默认训练；只有已完成人工标注的样本写入清单。
- `training/` 是原 ego-quality：YOLO26、官方初始权重、1024 图片尺寸、数据增强、argparse 参数；`TRAIN_DATA_URI` 指向标准 YOLO 目录。
- 权重写入平面的 `models/<YYYYMMDD-N>.pt`，日志写入 `runs/<run-id>/`。无编号预占、锁、控制状态文件。
- AI 标注选择同一数据集 `models/` 中的权重，支持单张和批量预标注；人工确认后才同步训练集。
- 不提供部署清单，不接入 CI 或自动 Review。K8s 部署由用户负责，SQLite 所在目录需挂载 PV。

## 已有验证

迁移前，在 DataFactory 工作目录使用本机 Python 完成：

- 后端 117 项测试通过，使用隔离 SQLite 和 Moto S3，覆盖上传、权限、标注、划分同步、S3 失败重试、AI 类别匹配、批量部分失败、重启中断。
- 真实本地 MinIO 验证上传、图片预览、YOLO 标签和三个清单、仅修改划分保留原标注。
- 真实 YOLO26 权重从 MinIO 加载，使用 CPU 完成单张预标注，保持样本为待标注；未进行 GPU 测试。
- 浏览器验证登录、任务列表、任务配置中的数据源和 AI 模型选择；前端生产构建通过。

完整 TypeScript 检查仍未通过：未修改的上游源码在相同依赖下有 130 条错误，本次当前源码也有 130 条。没有进行全量类型债务清理。

迁移后已在本仓库重新进行冻结安装与测试：117 项通过（Python 3.11），没有使用 GPU。

DataFactory 的源码及原方案删除已落到该工作区，尚未提交或推送其删除改动。

## 新会话接续

1. 从本仓库 README 开始，检查迁移后的 Git 状态和本地环境。
2. 后端验证：`uv sync --python 3.11 --frozen --group test`，然后 `uv run --no-sync pytest`。
3. 前端：进入 `frontend/`，`pnpm install --frozen-lockfile --ignore-scripts`，运行 frontend 的 postinstall 后启动或构建。
4. 继续 AI 验证时使用已有 PyTorch/Ultralytics 环境，显式指定 CPU；不要修改用户已有 AMD PyTorch 为 CPU 版本。

尚未验收私有镜像构建、真实 GPU 训练、真实模型的整批 AI 标注。迁移不代表这些验收已完成。

本轮在 Docker 中创建的隔离 MinIO 实例为 `datafactory-labelu-minio-0c91`，本机端口为 9000/9001，仅有合成验证数据。前后端曾运行于 8002/3004，迁移时停止旧路径进程。
