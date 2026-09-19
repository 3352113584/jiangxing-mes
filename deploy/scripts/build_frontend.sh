#!/bin/sh
# 构建前端静态资源到 deploy/frontend-dist/。
# 仅当 frontend/ 已含真实前端源码时使用。
# 需要 Docker：通过 frontend profile 临时构建并导出 dist。
set -e
cd "$(dirname "$0")/../.."
docker compose -f deploy/docker-compose.prod.yml --profile frontend up frontend
echo "前端资源已构建至 deploy/frontend-dist/（由网关 nginx 挂载并提供服务）"
