FROM node:24-bookworm-slim AS frontend

WORKDIR /labelu/frontend

RUN npm install --global pnpm@12.3.4 --registry=https://registry.npmmirror.com

COPY frontend/ ./

RUN pnpm install --frozen-lockfile --ignore-scripts \
    && pnpm --filter @labelu/frontend run postinstall \
    && pnpm build:frontend

FROM datafactory-cn-beijing.cr.volces.com/common/ultralytics

WORKDIR /labelu

RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ uv

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY labelu/ ./labelu/

# 复用基础镜像中的 PyTorch/Ultralytics，避免为 Web 依赖替换显卡运行环境。
RUN uv venv --system-site-packages .venv \
    && uv sync --frozen --no-dev

COPY --from=frontend /labelu/frontend/apps/frontend/dist/ ./labelu/internal/statics/

ENV PATH="/labelu/.venv/bin:$PATH" \
    DATABASE_URL="sqlite:////data/labelu.sqlite"

EXPOSE 8000

CMD ["uvicorn", "labelu.main:app", "--host", "0.0.0.0", "--port", "8000"]
