<p align="center">
  <img src="frontend/images/yolo-mcp-logo.svg" alt="YOLO MCP" width="200" />
</p>

# YOLO MCP

**在本地完成图片标注、AI 辅助标注与模型训练。**

YOLO MCP 面向目标检测数据集的日常迭代：上传图片，编辑和确认标注，划分训练集与测试集，再使用 YOLO26 训练模型。图片、标注、模型与日志保存在本地目录，适合在自己的工作站上管理数据和运行实验。

Python 发行包名为 `yolo-mcp`，源码模块为 `backend`，服务和离线训练命令分别为 `yolo-mcp`、`yolo-mcp-train`。

[快速开始](#快速开始) · [使用流程](#使用流程) · [模型与训练](#模型与训练) · [数据存储](#数据存储) · [开发](#开发) · [致谢](#致谢)

## 主要功能

- **项目管理**：独立配置标注类别、自动标注模型和训练默认参数；创建项目时自动建立数据目录。
- **图片标注**：批量上传图片，人工编辑标注，查看完成状态与标注数量。项目可先创建，稍后上传图片。
- **数据划分**：支持训练集和测试集；项目页展示各自数量，点击即可筛选。
- **AI 辅助标注**：使用项目模型或开放词汇模型生成候选框，再由人工检查、修改和确认。
- **模型训练**：在页面启动 YOLO26 目标检测训练，查看状态、参数、指标和日志，下载初始及产出权重。
- **历史管理**：单独清理训练日志，或删除整条训练记录及其产出模型。

当前接入的是图片目标检测流程，上传支持 JPG、PNG、BMP、WEBP 和 TIFF，服务端会检查实际图片内容。数据直接上传到项目，不需要配置外部数据源。

## 快速开始

### 准备环境

- Python **3.11 或更新版本**，以及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
- Node.js **24**、pnpm **12.3.4**，用于运行前端。
- 训练或 AI 推理需要额外的模型依赖；人工标注可以先使用轻量后端环境。

```bash
git clone https://github.com/killf/LabelS.git
cd LabelS
```

### 启动后端

```bash
cd backend
uv sync --python 3.11 --frozen --no-dev
cp .env.example .env
```

`.env` 中可以按需调整数据目录和计算设备。签名密钥在首次启动时自动生成并保存，后续启动复用，无需手动配置。

```bash
uv run --no-sync --env-file .env uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

首次启动会初始化数据库。默认数据位于用户主目录的 `.yolo-mcp/`；[API 文档](http://127.0.0.1:8002/docs) 可用于查看接口。

### 启动前端

在另一个终端，从仓库根目录执行：

```bash
cd frontend
pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts
pnpm --filter @yolo-mcp/frontend run postinstall
pnpm --filter @yolo-mcp/frontend start --host 127.0.0.1
```

打开 [http://127.0.0.1:3004](http://127.0.0.1:3004)，首次访问空库时点击“初始化管理员”。初始化完成后关闭公开注册，其他账号由管理员添加。开发服务器会将 API、WebSocket 和 MCP 请求转发到后端的 `8002` 端口。

## 使用流程

1. **创建项目**：填写名称，配置标注工具和类别。上传图片和选择 AI 模型都可以稍后进行。
2. **上传与划分**：批量上传图片，为样本选择训练集或测试集，默认进入训练集。
3. **完成标注**：手动标注，或运行 AI 批量标注后检查预测结果。AI 结果经人工确认后才计为已完成。
4. **配置训练**：在“模型设置”中保存算法、初始权重、Epoch、学习率和自定义参数。
5. **训练与迭代**：在项目页点击“开始训练”，按需修改本次参数。点击弹窗标题旁的历史图标查看训练记录，下载权重或检查日志。

开始训练前，训练集和测试集都需要至少一张已完成标注的图片。训练产出的权重可以在项目模型设置中选为自动标注模型，继续辅助下一轮数据标注。

## 用户与项目权限

点击右上角账号菜单进入“用户管理”或“访问令牌 / MCP”。管理员可以添加账号、设置系统角色、启停账号和重置密码；停用或重置密码会撤销旧会话与个人令牌。系统始终保留至少一名启用的管理员。

| 身份       | 权限                                                     |
| ---------- | -------------------------------------------------------- |
| 系统管理员 | 管理全部用户、项目和访问令牌                             |
| 项目拥有者 | 配置项目、添加或移除协作者、上传、标注、训练、下载及删除 |
| 项目协作者 | 查看、上传、标注、运行 AI 标注、训练和下载               |

普通用户可以创建自己的项目，不能访问其他用户尚未共享的项目。拥有者通过项目页的“项目成员”分配协作者；配置、成员管理和正式数据删除仍由拥有者或管理员执行。协作者可以撤回本人尚未提交成样本的上传。

## MCP 接入

服务在 `/mcp` 提供 **Streamable HTTP**。先在“访问令牌 / MCP”创建个人访问令牌，设置名称和有效期；明文仅在创建时显示一次，数据库只保存摘要。客户端需支持手动设置 Authorization 请求头，本版本不提供 OAuth 登录授权或 stdio。

以已经包含前端的服务地址为例：

```json
{
  "mcpServers": {
    "yolo-mcp": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer <个人访问令牌>"
      }
    }
  }
}
```

上例适用于采用此配置结构的客户端，具体字段以客户端文档为准。源码开发也可直接连接 `http://127.0.0.1:8002/mcp`。

工具覆盖项目、图片上传、标注、AI 批次、训练、日志和模型下载。上传接收 Base64 图片内容；模型下载工具返回需携带同一令牌的 HTTP 接口路径。所有工具与网页共用项目权限，令牌不单独扩大权限；撤销、过期或账号停用后，后续调用立即拒绝。令牌不能用于继续创建令牌或管理账号，请登录网页执行凭据管理。

默认仅接受本机 Host / Origin。远程部署时设置 `MCP_ALLOWED_HOSTS` 和 `MCP_ALLOWED_ORIGINS` 为实际域名的 JSON 数组，并通过 HTTPS 代理访问。不要将个人令牌写入仓库。

## 模型与训练

### 自动标注模型

项目的“模型设置”提供以下选项。模型在后端进程中按需加载，运行前需准备对应依赖和权重。

| 算法                      | 权重来源                                                   | 使用说明                                                     |
| ------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------ |
| YOLO26 目标检测           | 当前项目 `models/` 下的 `.pt` 文件                         | 使用训练产物或预先放入的项目权重                             |
| Florence-2                | `microsoft/Florence-2-base` / `microsoft/Florence-2-large` | 使用本地 Hugging Face 缓存，根据项目类别生成候选框           |
| GroundingDINO + SAM ViT-B | `IDEA-Research/grounding-dino-tiny`                        | 当前矩形流程使用 GroundingDINO 检测分支，不加载 SAM 分割权重 |
| SAM 3                     | `facebook/sam3`                                            | 额外安装官方 `sam3` 包，并提前缓存 `sam3.pt`                 |

YOLO 标注与训练使用后端的 `training` 可选依赖；开放词汇模型的通用依赖位于 `annotation` 可选依赖中，具体版本见 [pyproject.toml](backend/pyproject.toml)。在已准备好兼容 PyTorch（`>=2.9,<3`）和 torchvision 的环境中，从仓库根目录按需安装：

```bash
python -m pip install -e "./backend[training]"
# 需要开放词汇标注模型时，再安装通用推理依赖。
python -m pip install -e "./backend[annotation]"
```

SAM 3 还需按照[官方仓库](https://github.com/facebookresearch/sam3)单独安装。

GPU 环境需要与硬件匹配的 PyTorch。已有 CUDA 或 AMD ROCm 环境时，应使用该环境启动后端，并保留其 GPU 运行时。例如，在仓库根目录使用已有环境的 `python` 执行：

```bash
python -m pip install -e ./backend
python -m uvicorn backend.main:app --env-file backend/.env --host 127.0.0.1 --port 8002
```

上述命令安装后端基础依赖；训练和推理依赖需在同一环境中另行准备。默认数据目录不随启动位置变化；设置 `DATA_DIR` 时可使用绝对路径或以 `~` 开头的主目录路径。

开放词汇模型只读取已准备好的本地缓存，标注请求不会下载模型或安装依赖。YOLO 官方初始权重首次用于训练时可能由 Ultralytics 下载。模型文件和代码的使用条件以各模型的许可为准。

### 训练参数与记录

当前训练算法为 **YOLO26 目标检测**，可选择官方初始权重或本项目模型。项目保存的配置会作为训练弹窗默认值，本次修改仅保存在该次训练记录中。

自定义训练参数使用 JSON 对象，例如：

```json
{
  "optimizer": "AdamW",
  "amp": false
}
```

点击参数标题后的“？”可以搜索可用参数、默认值与说明。基础表单字段、模型、设备及项目路径由系统管理，不能在 JSON 中重复覆盖；学习率对应 `lr0`，使用 `optimizer=auto` 时由框架决定实际学习率。

每次训练保留输入快照和实际参数，并记录等待、运行中、成功、失败或中断状态。点击记录中的参数摘要查看详情，点击权重名称下载模型。服务重启后，未完成的训练会标为中断，不会自动重跑。

测试集同时用于每轮验证和最优模型选择，`val` 与 `test` 都指向 `test.txt`，因此记录中的指标不是独立测试成绩。

- **清理日志**：移除本次运行目录（包括数据快照、日志和中间文件），保留记录、指标及产出模型。
- **删除**：移除训练记录、产出模型及剩余日志。运行中或仍在使用的模型不能删除。

离线训练、命令行参数和数据格式见[训练说明](backend/training/README.md)。

## 数据存储

`DATA_DIR` 指定数据根目录，默认是用户主目录下的 `~/.yolo-mcp/`。SQLite 默认保存在同一目录，也可用 `DATABASE_URL` 单独指定。

```text
~/.yolo-mcp/
├── secret.key            # 首次启动生成，之后复用的签名密钥
├── labels.sqlite
└── projects/<项目 ID>/
    ├── images/           # 上传原图和缩略图
    ├── models/           # 项目模型权重
    └── runs/<记录 ID>/
        ├── dataset/      # 本次训练开始时生成的独立快照
        │   ├── images/
        │   ├── labels/
        │   ├── train.txt
        │   ├── test.txt
        │   └── data.yaml
        ├── console.log
        ├── train.log
        └── training/     # 框架指标和中间权重
```

人工标注、类别配置和数据划分保存在数据库中；项目目录不预先生成训练清单或 YOLO 副本。每次开始训练时，按当时的配置和已完成样本生成独立数据集，未完成、跳过或已删除的样本不进入清单，背景图片生成空标签。旋转只作用于 run 内的训练副本，原图保持原样；后续修改项目不会改变已生成的快照。

新上传统一写入 `images/`。旧附件仍按数据库记录的路径读取，已有 `uploads/` 不会自动移动或删除。项目改名不影响数据目录。

每个上传附件只对应一个样本，重复提交返回冲突，不会创建重复数据。删除样本会同时删除原图和缩略图；已创建样本的附件须从样本列表删除。

| 配置项           | 用途                                                               |
| ---------------- | ------------------------------------------------------------------ |
| `DATA_DIR`       | 图片、模型、训练日志和默认数据库的根目录                           |
| `DATABASE_URL`   | 数据库连接地址，未指定时使用本地 SQLite                            |
| `USE_AUTO_LABEL` | 是否启用 AI 自动标注，默认开启                                     |
| `DEVICE`         | 推理设备；留空自动选择，`0` 表示首块 CUDA/ROCm GPU，也可指定 `cpu` |

备份时请保留整个数据目录，包括 `secret.key`、数据库和项目文件；保留密钥可让登录令牌和图片签名跨重启继续使用。仓库只维护 [001_init_db.py](backend/migrations/versions/001_init_db.py) 初始化脚本，当前不提供历史数据库结构升级或数据搬迁工具。结构调整后需使用新数据库；重复执行 init 不会改造已有数据库。SQLite 连接启用外键约束。

## 打包与安装

从完整源码仓库构建发行包。先按“快速开始”准备前端依赖，再在仓库根目录执行：

```bash
uv build --project backend --out-dir dist
```

构建会重新编译前端，生成源码包和包含页面资源的 wheel。将 wheel 复制到目标机器后安装，无需 Node.js 或 pnpm：

```bash
python -m pip install ./dist/yolo_mcp-2.0.0-py3-none-any.whl
yolo-mcp --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000) 即可使用。源码包也包含编译后的页面，可直接通过 pip 安装。GPU 训练和推理仍需准备对应的可选依赖与权重。

开发模式使用 `python -m pip install -e ./backend`，并单独启动前端开发服务器；可编辑安装跳过前端编译。

## Docker

仓库维护一个 [Dockerfile](Dockerfile)，同时构建前端和后端。GPU 运行环境使用 `ultralytics/ultralytics` 基础镜像。

```bash
docker build -t yolo-mcp:local .
```

将下方路径替换为已创建的数据目录后运行，容器通过 `DATA_DIR=/data` 使用挂载目录保存数据和签名密钥：

```bash
docker run --rm -p 8000:8000 \
  --mount type=bind,source=/absolute/path/to/data,target=/data \
  yolo-mcp:local
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。镜像已包含前端，无需另启开发服务器。离线训练可使用同一镜像的 `yolo-mcp-train` 入口，示例见[训练说明](backend/training/README.md#共用服务镜像)。GPU 可用性取决于基础镜像和宿主机运行环境。

## 开发

```text
backend/             Python 后端、推理与训练模块
  migrations/        数据库初始化
  tests/             后端测试
frontend/            前端应用与组件工作区
Dockerfile           共用构建入口
```

在后端目录安装测试依赖并执行测试：

```bash
cd backend
uv sync --python 3.11 --frozen --group test
uv run --no-sync pytest
```

前端检查与构建：

```bash
cd frontend
pnpm --filter @yolo-mcp/frontend test:unit
pnpm --filter @yolo-mcp/frontend type-check
pnpm lint 'apps/frontend/src/**/*.{ts,tsx}'
pnpm build:frontend
```

后端测试使用隔离 SQLite 和临时数据目录。前端构建、类型检查和单元测试是独立步骤。提交修改时请说明验证结果；反馈问题可使用 [GitHub Issues](https://github.com/killf/LabelS/issues)，附上复现步骤、版本和相关日志。

## 致谢

YOLO MCP 基于以下开源项目开发：

- [LabelU](https://github.com/opendatalab/labelU)：后端基础，源版本 `1.5.6`，提交 `8681ca4`。
- [LabelU-Kit](https://github.com/opendatalab/labelU-Kit/tree/v5.12.0)：前端与标注组件，源版本 `v5.12.0`，提交 `d06cb1f5`。
- [Ultralytics](https://github.com/ultralytics/ultralytics)：YOLO 模型训练与推理。

Florence-2、GroundingDINO + SAM 和 SAM 3 的标注接入参考了 [LabelU 模型服务](https://github.com/opendatalab/labelU/blob/main/model_server/README.md)。感谢上述项目及其贡献者。

## 许可证

项目使用 [Apache-2.0 许可证](LICENSE)，前端保留其[上游许可证](frontend/LICENSE)。第三方依赖、模型代码和权重遵循各自许可。
