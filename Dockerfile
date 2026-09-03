# OmniNAV 生产镜像：多阶段构建（前端产物 + 后端依赖），单容器由 FastAPI 同源托管前端
# 构建上下文 = 仓库根目录：docker build -t omninav:latest .

# ---------- 阶段 1：前端构建 ----------
FROM node:22-alpine AS frontend
WORKDIR /build
# 国内网络可走镜像源；海外环境删掉 --registry 参数即可
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端依赖（带编译器兜底个别无 cp314 wheel 的包） ----------
FROM python:3.14-slim AS backend-deps
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY backend/requirements.lock.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt

# ---------- 阶段 3：运行时 ----------
FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
# 目录布局保持 <root>/backend + <root>/frontend/dist，
# app/main.py 按相对路径定位前端产物，代码零改动
COPY --from=backend-deps /opt/venv /opt/venv
COPY backend/ /opt/omninav/backend/
COPY --from=frontend /build/dist /opt/omninav/frontend/dist
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /opt/omninav/backend
EXPOSE 8000
# 启动前先跑迁移（首启时由 INIT_ADMIN_PASSWORD 播种管理员）；必须单 worker
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
