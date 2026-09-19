# 匠星智造 MES 前端生产构建（多阶段）。
#
# 说明：当前仓库 frontend/ 仅含占位文件（.gitkeep）。
# 当真实前端源码（React + Vite + AntD）纳入本仓库后，启用本镜像：
#   docker compose -f deploy/docker-compose.prod.yml --profile frontend up frontend
# 构建产物会写入挂载卷 ./frontend-dist，由网关 nginx 提供静态服务。
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ .
# API 基础路径：同源 /api（由网关代理到 backend），无需跨域
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# 仅输出 dist 到挂载卷 /dist
CMD ["sh", "-c", "cp -r dist/* /dist/ 2>/dev/null || true"]
