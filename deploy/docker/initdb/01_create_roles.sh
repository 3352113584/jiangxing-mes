#!/bin/sh
# ============================================================
# 匠星智造 MES — PostgreSQL 首次初始化角色创建脚本
# ============================================================
# 由 postgres 容器在【首次初始化】（数据卷 mes_postgres_data 为空）时，
# 以 POSTGRES_USER（Postgres 镜像管理员）身份自动执行。
#
# 目的：建立独立的迁移角色 mes_migration 与应用最小权限角色 mes_app，
#       使生产部署满足账号分离 —— 应用/迁移均不复用镜像管理员账号。
#
# 重要说明：
#   1. 本脚本仅在数据卷为空（首次 init）时执行一次。
#      若部署到【已存在】的数据库，需由 DBA 手工执行等价语句（见文末）。
#   2. mes_app 的细粒度权限（SELECT/INSERT/部分 UPDATE）由 Alembic 迁移
#      NB-1 (e9a3b5c7d921) 授予；此处仅负责建角色与设置口令。
#   3. mes_migration 接管数据库所有权，以便执行 DDL/迁移
#      （含 public 模式下的 alembic_version 与公共函数；PostgreSQL 15+
#       下 public 模式的 CREATE 权限默认仅数据库所有者拥有）。
#   4. 口令来自环境变量（deploy/.env），绝不硬编码；经 psql -v 注入，
#      由 psql 自动转义特殊字符（含单引号），避免注入。
#
# 等价手工语句（已有数据库时由 DBA 执行）：
#   CREATE ROLE mes_migration LOGIN PASSWORD '<mig_pw>'
#     CREATEROLE NOCREATEDB NOSUPERUSER;
#   CREATE ROLE mes_app LOGIN PASSWORD '<app_pw>';
#   ALTER DATABASE <db> OWNER TO mes_migration;
#   GRANT CONNECT ON DATABASE <db> TO mes_migration, mes_app;
# ============================================================
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v mig_pw="$MES_MIGRATION_PASSWORD" -v app_pw="$MES_APP_PASSWORD" -v db="$POSTGRES_DB" <<'EOSQL'
  -- 1) 迁移专用角色：可建角色、不可建库、非超级用户、仅承担迁移/DDL
  DO $$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_migration') THEN
      CREATE ROLE mes_migration LOGIN PASSWORD :'mig_pw' CREATEROLE NOCREATEDB NOSUPERUSER;
    END IF;
    -- 2) 应用最小权限角色：无建角色/建库/超级权限，权限由 NB-1 迁移授予
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_app') THEN
      CREATE ROLE mes_app LOGIN PASSWORD :'app_pw';
    END IF;
  END
  $$;

  -- 3) 迁移角色接管数据库所有权，确保可创建 schema/表/序列 及 public 下的对象
  ALTER DATABASE :"db" OWNER TO mes_migration;

  -- 4) 允许两个角色连接数据库
  GRANT CONNECT ON DATABASE :"db" TO mes_migration, mes_app;
EOSQL

echo "[initdb] mes_migration / mes_app roles ensured; database owner set to mes_migration."
