# LabelS 标注与训练

![LabelS](frontend/images/labels-logo.svg)

图片上传、人工标注、YOLO 辅助标注和本机训练。所有数据直接保存到本地目录，不配置数据源，不使用 S3，也不提供图片或预标注导入。

## 目录与数据

后端是独立 Python 项目 `backend/`，前端位于 `frontend/`，训练模块位于 `backend/training/`。版本为 `2.0.0`。

`BASE_DATA_DIR` 指定本地数据根目录，默认 `data/`，相对于服务启动目录。SQLite 默认位于该目录的 `labels.sqlite`，也可用 `DATABASE_URL` 单独指定。

```text
data/
├── labels.sqlite
└── tasks/<任务ID>/
    ├── uploads/             # 上传图片和缩略图
    ├── images/              # 已确认的 YOLO 图片
    ├── labels/              # YOLO 标签
    ├── train.txt
    ├── test.txt
    ├── data.yaml
    ├── models/              # 可选择、下载的任务模型
    └── runs/<训练记录ID>/   # 日志、输入快照及训练中间文件
```

创建任务时自动创建目录，任务改名不移动文件。目录创建失败则回滚任务；图片只接受 JPG、PNG、BMP、WEBP、TIFF，服务端验证实际图片内容。

样本只分训练集和测试集，默认训练集。人工保存后同步 YOLO 图片、标签和清单，未完成或跳过的样本不进入清单；背景样本保存空标签。保存先写入数据库，再更新本地数据集；磁盘失败时返回错误，原标注仍可重新保存重试。

## 模型设置与训练

任务配置分四步：基础配置、图片上传、标注配置、模型设置。首版算法为 YOLO 目标检测，模型从当前任务 `models/` 选择。AI 预测框可编辑，人工确认前不算完成标注。

任务页提供“开始训练”和“训练记录”。训练集和测试集都需要至少一张已确认图片。可设置初始权重、轮数、图片尺寸与 batch，后台复用当前 Python 的 PyTorch/Ultralytics 环境执行独立训练进程，不在请求中安装依赖或替换 GPU 运行时。

只维护 `train.txt` 和 `test.txt`。YOLO 的 `val` 与 `test` 同时指向 `test.txt`，测试集用于每轮验证及选择 `best.pt`，因此展示的指标不是独立测试成绩。每次训练先复制输入快照，产出模型保存到当前任务的 `models/`。

训练记录显示等待、运行中、成功、失败或中断状态，并提供参数、指标、日志和模型下载。正常关闭服务会终止自己启动的训练；重新启动后未完成记录标为中断，不自动重跑。

- **清理日志**：删除该次运行的日志和中间文件，保留执行记录、指标与产出模型。
- **清理记录**：删除执行记录、产出模型及剩余日志。被 AI 配置或其他运行任务引用的模型需先解除使用。

任务创建者可清理终态记录，运行中的训练不允许清理。数据库与 `BASE_DATA_DIR` 应一起备份；目录路径不要指向不受信任的可写共享位置。

## 本地运行

仅运行人工标注可使用后端轻量环境：

```bash
cd backend
uv sync --python 3.11 --frozen --group test
cp .env.example .env
uv run --env-file .env uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

启用训练或 AI 时，优先复用已安装 PyTorch/Ultralytics 的 GPU 环境。本机已有 AMD Python 可从仓库根目录运行：

```powershell
$env:BASE_DATA_DIR = 'C:/Users/killf/github/LabelS/backend/data'
$env:PASSWORD_SECRET_KEY = '<自行生成的固定签名密钥>'
$env:AI_DEVICE = '0'
C:/Python314/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

前端：

```bash
cd frontend
pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts
pnpm --filter @labels/frontend run postinstall
pnpm --filter @labels/frontend start --host 127.0.0.1
```

访问 `http://127.0.0.1:3004/`，开发服务器将 API 和 WebSocket 转发到后端 8002。图片预览使用限定文件、带有效期的地址；模型下载和训练操作需登录并具有任务访问权。

当前仅保留 `backend/migrations/versions/001_init_db.py` 初始化空库，不提供旧结构迁移或 to_mysql。结构调整后使用新库，已有数据库和原 S3 数据不自动搬迁或删除。

## 验证与构建

```bash
cd backend
uv run --no-sync pytest
cd ../frontend
pnpm --filter @labels/frontend test:unit
pnpm build:frontend
pnpm --filter @labels/frontend type-check
```

测试使用隔离 SQLite 和临时本地目录，不读取真实凭据。完整 TypeScript 检查仍有既有页面/组件类型问题，构建与类型检查分别报告。不接入 CI 或自动 Review，测试按需执行。

只维护根目录的 `Dockerfile`，从仓库根目录执行 `docker build -t labels:local .`。同一镜像默认启动标注服务，持久化 `/data`；离线训练使用 `--entrypoint labels-train`，参数与挂载约定见[训练说明](backend/training/README.md)。

依赖清单和锁文件先于源码复制，前后端依赖分别形成缓存层；pnpm、pip 和 uv 使用 BuildKit 缓存挂载。只改业务源码时复用依赖层，继续执行项目安装和源码构建。GPU 框架沿用 Ultralytics 基础镜像。

## 参考项目

后端基于 [LabelU](https://github.com/opendatalab/labelU)，提交 `8681ca4`，版本 1.5.6；前端复制自 [LabelU-Kit v5.12.0](https://github.com/opendatalab/labelU-Kit/tree/v5.12.0)，提交 `d06cb1f5`。两份 Apache-2.0 许可证分别保留在本目录与 `frontend/`。未引入上游 Git 仓库、发布流水线和模型权重。
