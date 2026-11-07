FROM node:24-bookworm-slim AS frontend

WORKDIR /labels/frontend

RUN npm install --global pnpm@12.3.4 --registry=https://registry.npmmirror.com

COPY frontend/ ./

RUN pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts \
    && pnpm --filter @labels/frontend run postinstall \
    && pnpm build:frontend

FROM datafactory-cn-beijing.cr.volces.com/common/ultralytics

WORKDIR /app/backend

RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ uv

COPY backend/ ./

# 复用基础镜像中的 PyTorch/Ultralytics，避免为 Web 依赖替换显卡运行环境。
RUN uv venv --system-site-packages .venv \
    && uv sync --frozen --no-dev

COPY --from=frontend /labels/frontend/apps/frontend/dist/ ./statics/

ENV PATH="/app/backend/.venv/bin:$PATH" \
    DATABASE_URL="sqlite:////data/labelu.sqlite"

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
