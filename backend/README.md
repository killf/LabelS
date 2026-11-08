# YOLO MCP 后端

本目录是独立 Python 项目，源码包名为 `backend`。业务说明、前端运行和参考项目见[仓库 README](../README.md)。

## Web 服务

从本目录执行：

```bash
uv sync --python 3.11 --frozen --group test
cp .env.example .env
# 按需调整 DATA_DIR、USE_AUTO_LABEL 和 DEVICE；签名密钥首次启动时自动生成。
uv run --env-file .env uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

`yolo-mcp` 也是服务 CLI 入口。模块导入和 `--help` 不初始化数据库，实际应用启动时通过 `migrations/versions/001_init_db.py` 初始化空库；默认 SQLite 文件名为 `labels.sqlite`。结构调整后使用新库，旧库不会自动迁移。不提供历史结构升级或 to_mysql。

`DATA_DIR` 默认指向用户主目录的 `.yolo-mcp/`。服务首次启动时在此目录生成 `secret.key`，后续启动读取同一密钥；数据库和项目文件也默认保存在此目录。

空库允许一次网页初始化管理员，完成后由管理员添加其他账号。个人令牌在网页管理，MCP 使用 Streamable HTTP `/mcp` 和 `Authorization: Bearer <个人令牌>`；不提供 OAuth 流程。项目拥有者管理配置和成员，协作者可以标注及训练，系统管理员管理全部项目。详细用法见[用户权限与 MCP 接入](../README.md#用户与项目权限)。

## 训练与 AI 预标注

项目页可发起异步训练并查看状态、日志与产物，项目配置第 4 步选择 YOLO 算法和 AI 模型。训练代码位于 `training/`，离线入口为 `yolo-mcp-train` 或 `python -m backend.training.train`。默认 Web 依赖不包含 PyTorch/Ultralytics，需要时安装 `.[training]`；优先复用已有 GPU 运行环境。安装和存储约定见[训练说明](training/README.md)。

服务与训练共用根目录的 Dockerfile，从仓库根目录构建：

```bash
docker build -t yolo-mcp:local .
```

## 验证

```bash
uv run --no-sync pytest
```

测试使用隔离 SQLite 和临时本地目录，不读取实际凭据。格式采用 Black（Python 3.11、88 列），核心链路同时执行 Flake8 检查。
