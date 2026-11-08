# LabelS 后端

本目录是独立 Python 项目，源码包名为 `backend`。业务说明、前端运行和参考项目见[仓库 README](../README.md)。

## Web 服务

从本目录执行：

```bash
uv sync --python 3.11 --frozen --group test
cp .env.example .env
# 填写 本地目录_* 并设置固定 PASSWORD_SECRET_KEY。
uv run --env-file .env uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

`labels` 也是服务 CLI 入口。模块导入和 `--help` 不初始化数据库，实际应用启动时通过 `migrations/versions/001_init_db.py` 初始化空库；默认 SQLite 文件名为 `labels.sqlite`。结构调整后使用新库，旧库不会自动迁移。不提供历史结构升级或 to_mysql。

## 训练与 AI 预标注

项目页可发起异步训练并查看状态、日志与产物，项目配置第 4 步选择 YOLO 算法和 AI 模型。训练代码位于 `training/`，离线入口为 `labels-train` 或 `python -m backend.training.train`。默认 Web 依赖不包含 PyTorch/Ultralytics，需要时安装 `.[training]`；优先复用已有 GPU 运行环境。安装和存储约定见[训练说明](training/README.md)。

服务与训练共用根目录的 Dockerfile，从仓库根目录构建：

```bash
docker build -t labels:local .
```

## 验证

```bash
uv run --no-sync pytest
```

测试使用隔离 SQLite 和临时本地目录，不读取实际凭据。格式采用 Black（Python 3.11、88 列），核心链路同时执行 Flake8 检查。
