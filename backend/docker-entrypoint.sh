#!/bin/sh
# 后端容器入口：先幂等执行迁移，再启动 uvicorn。
# 迁移变量 MES_MIGRATION_DATABASE_URL 由 docker-compose.prod.yml 注入。
set -e

echo "[entrypoint] applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting uvicorn on 0.0.0.0:8000 ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
