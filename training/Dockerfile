# 1. 使用私有化 Ultralytics 基础镜像，设置独立项目的运行目录。
FROM datafactory-cn-beijing.cr.volces.com/common/ultralytics

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    YOLO_AUTOINSTALL=false \
    YOLO_CONFIG_DIR=/workspace/.ultralytics \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

WORKDIR /app

# 2. 准备 OpenCV 运行库和 Python 包管理器，其余框架组件复用基础镜像。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ uv==0.12.10

# 3. 安装项目到基础镜像环境，复用其中满足版本要求的 PyTorch。
COPY pyproject.toml README.md ./
COPY src/ ./src/

# 构建阶段没有显卡驱动，不启用本机后端探测，防止误判为 CPU 环境。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-config \
        --default-index https://mirrors.aliyun.com/pypi/simple/ .

# 4. 启动训练，轮数、batch 等参数在运行时由命令行传入。
ENTRYPOINT ["ego-quality-train"]
CMD ["--work-dir", "/workspace"]
