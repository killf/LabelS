# LabelS 标注与训练

![LabelS](frontend/images/labels-logo.svg)

用于独立算法数据集的图片标注。离线训练代码位于 [backend/training](backend/training/README.md)。不接入 CI 和自动 Review，测试按需运行。

## 目录

```text
LabelS/
├── backend/                 # 独立 Python 后端项目，同时是 backend 包
│   ├── main.py              # 服务与 CLI 入口
│   ├── migrations/          # 001_init_db.py 完整初始化脚本
│   ├── training/            # 离线训练模块，GPU 依赖按需安装
│   ├── tests/               # SQLite / Moto S3 验证
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/                # 管理页面、标注组件及文档图片
└── Dockerfile               # 包含前端静态文件的标注平台镜像
```

## 参考项目

后端基于 [LabelU](https://github.com/opendatalab/labelU)，提交 `8681ca4`，版本 1.5.6；前端复制自 [LabelU-Kit v5.12.0](https://github.com/opendatalab/labelU-Kit/tree/v5.12.0)，提交 `d06cb1f5`。两份 Apache-2.0 许可证分别保留在本目录与 `frontend/`。未引入上游 Git 仓库、发布流水线和模型权重。

## 存储与数据集

- SQLite 保存账户、任务、原始标注和数据集划分；`DATABASE_URL` 指定文件位置。
- 上传的图片和缩略图存入全局 `S3_*` 配置的桶，移除了本地媒体存储后端。
- 每个任务选择自己的 S3 数据源与数据集目录。目录相对于该数据源的前缀，不同任务使用独立目录。
- 图片标注保存后直接同步 YOLO 数据集，不提供导出入口、导出任务或下载包。
- 当前同步目标为图片目标检测，标注工具使用矩形框；类别顺序由任务配置决定，类别显示名称写入 `data.yaml`。

```text
<数据源前缀>/<数据集目录>/
├── images/<sample-id>.<ext>
├── labels/<sample-id>.txt
├── train.txt        # 训练
├── test.txt         # 测试
├── val.txt          # 评估
└── data.yaml
```

样本默认归入训练集，可在样本列表选择训练、测试或评估。清单只包含已完成的样本；撤回、跳过或删除时同步移除对应训练文件和清单引用。空标注保存为空标签文件，用作背景样本。

保存先写入 SQLite，再同步变更图片、标签和三个清单；修改任务配置时同步全部样本。S3 失败会返回明确错误，已保存的标注仍在 SQLite 中，重新保存即可重试。这里不提供跨 SQLite/S3 的原子发布协议；训练应在本次标注和同步完成后启动。

从外部 S3 数据源导入的图片只读取，删除样本引用时不删除原图。`raw/`、`models/` 和 `runs/` 不由标注同步流程清理。独立数据集直接使用 S3，项目不依赖 DataFactory 服务。

## AI 预标注

任务配置中的“AI 模型”列出目标数据集 `models/` 下的 `.pt` 权重。选择权重后，可在标注页对单张图片生成预标注，也可在任务页面批量处理待标注样本。

- 使用 YOLO26，类别按任务显示名称或内部值匹配；未匹配的预测类别会忽略并提示。
- 预测框只作为可编辑的预标注，不自动把样本标为完成；人工确认保存后才同步训练数据。
- 每批只加载一次模型，逐张保存结果并记录成功、失败数量；重启后未完成批次标记为中断。
- `AI_DEVICE` 留空时由 PyTorch 选择设备，验证时可显式设为 `cpu`。
- 不再支持原上游的 HTTP 模型服务分支。AI 预标注和离线训练使用同一组可选 `training` 依赖，默认 Web 安装不包含 PyTorch/Ultralytics。

## 本地运行

后端使用本地 Python。仅运行标注界面时可使用独立轻量环境；启用 AI 标注时，在已有 PyTorch/Ultralytics 的训练环境中安装本项目。

```bash
cd C:/Users/killf/github/LabelS/backend
uv sync --python 3.11 --frozen --group test
cp .env.example .env
# 填写 S3_*，设置固定 PASSWORD_SECRET_KEY 后启动
uv run --env-file .env uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

另一个终端启动前端：

```bash
cd frontend
pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts
pnpm --filter @labels/frontend run postinstall
pnpm --filter @labels/frontend start --host 127.0.0.1
```

访问 `http://127.0.0.1:3004/`。开发服务器将 API 与 WebSocket 请求转发到本地 8002 端口。先在“数据源”中配置 S3 连接，再创建标注任务并选择目标数据源、填写数据集目录。

本地 MinIO 可以使用已有镜像启动，并把 S3 endpoint 设置为 `http://127.0.0.1:9000`，启用 path-style；桶需预先创建。以下命令只供本地合成数据使用：

```bash
docker run -d --pull never --name labels-minio \
  -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
  -e MINIO_ROOT_USER=labels-local -e MINIO_ROOT_PASSWORD=labels-local-only \
  -v labels-minio:/data minio/minio:latest server /data --console-address :9001
```

后端 Python 包为 `backend`，服务命令为 `labels`，训练命令为 `labels-train`，前端内部包使用 `@labels/*` 并链接本地源码，不从 npm 下载。已有数据库继续使用 `labelu.sqlite`；已有 `DATABASE_URL` 无需改动。浏览器语言与播放偏好键保持兼容。

固定的 `PASSWORD_SECRET_KEY` 同时用于登录签名与 S3 数据源凭据加密，重启后应保留同一配置。

## 验证与构建

```bash
cd backend
uv run --no-sync pytest
cd ../frontend
pnpm build:frontend
```

测试使用隔离 SQLite 和 Moto 模拟 S3，不读取实际凭据、不连接外部存储。实际 MinIO 与浏览器验证另行执行。

本地包的运行与类型入口都指向工作区源码。完整 TypeScript 检查仍有 74 条页面/组件类型错误，本轮已消除全部模块缺失错误；生产构建与完整类型检查的结果分开报告。

Python 修改文件按 Black（Python 3.11、88 列）格式化，并用 Flake8 检查。前端工具函数使用现有 ESLint/Prettier 检查；`lint:*` 默认只检查，不自动修改文件。使用当前 Node 24 环境执行新增前端单元测试：

```bash
cd frontend
pnpm --filter @labels/frontend test:unit
pnpm --filter @labels/frontend type-check
```

安装命令明确跳过第三方生命周期脚本，`strictDepBuilds=false` 仅允许被跳过的脚本不使安装失败，不授予执行许可。前端的主题 CSS 仍通过前述显式 postinstall 命令生成。

标注平台镜像从本目录构建：

```bash
docker build -t labels:local .
```

训练镜像使用 `backend/Dockerfile.training`，构建上下文为 `backend/`，详细参数与 S3 模型、日志约定见 [训练说明](training/README.md)。

## SQLite 持久化

`DATABASE_URL` 可设为 `sqlite:////data/labelu.sqlite`。部署到 K8s 时，将整个 `/data` 目录挂载到 PV，使数据库和 journal 一起持久化。部署由使用方维护，本项目不提供部署清单。

后端版本为 `2.0.0`。`backend/migrations/versions/` 仅保留一份完整初始化脚本，启动时由 Alembic 建立空库表结构；不提供历史修订链升级或 SQLite 到 MySQL 的搬迁命令。
