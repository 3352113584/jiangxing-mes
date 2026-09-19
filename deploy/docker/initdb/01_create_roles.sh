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
#
#   4. 口令传递方式（安全要求）：
#      绝不在 PostgreSQL 的美元引用块（DO $$ ... $$）内使用 psql 变量语法
#      :'var' —— 美元引用块内的内容对 psql 是不透明字符串，' :var ' 不会被
#      插值，语句原样送交服务端后会报
#        ERROR: syntax error at or near ":"
#      从而导致角色从未被创建、账号分离在生产实际失效。
#
#      本脚本改用：psql 变量插值（:'mig_pw'，位于美元引用块【之外】）
#      → format(%L) 生成带安全引用的 SQL 文本 → \gexec 执行该文本。
#      format 的 %L 会按 SQL 字面量规则转义（含单引号、反斜杠），
#      因此口令即使包含 ' 或 \ 也不会破坏语句，不存在 SQL 注入。
#
#   5. 角色属性（不可放宽）：
#      mes_migration : LOGIN, NOSUPERUSER, CREATEROLE, NOCREATEDB
#      mes_app       : LOGIN, NOSUPERUSER, NOCREATEROLE, NOCREATEDB
#      两者均不是数据库 owner 之外的额外特权；数据库 owner 为 mes_migration。
#
# 等价手工语句（已有数据库时由 DBA 执行）：
#   CREATE ROLE mes_migration LOGIN PASSWORD '<mig_pw>'
#     CREATEROLE NOCREATEDB NOSUPERUSER;
#   CREATE ROLE mes_app LOGIN PASSWORD '<app_pw>'
#     NOSUPERUSER NOCREATEROLE NOCREATEDB;
#   ALTER DATABASE <db> OWNER TO mes_migration;
#   GRANT CONNECT ON DATABASE <db> TO mes_migration, mes_app;
# ============================================================
set -e

# 口令必须由 deploy/.env 注入；缺失时立即失败，避免建出空口令账号。
: "${MES_MIGRATION_PASSWORD:?MES_MIGRATION_PASSWORD 必须在 deploy/.env 中设置}"
: "${MES_APP_PASSWORD:?MES_APP_PASSWORD 必须在 deploy/.env 中设置}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v mig_pw="$MES_MIGRATION_PASSWORD" -v app_pw="$MES_APP_PASSWORD" -v db="$POSTGRES_DB" <<'EOSQL'
\set ON_ERROR_STOP on

-- 1) 迁移专用角色：可建角色、不可建库、非超级用户、仅承担迁移/DDL
SELECT format(
         'CREATE ROLE mes_migration LOGIN PASSWORD %L CREATEROLE NOCREATEDB NOSUPERUSER',
         :'mig_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_migration')
\gexec

-- 1b) 幂等：角色已存在时同步口令并重申属性边界（不放大权限）
SELECT format(
         'ALTER ROLE mes_migration WITH LOGIN PASSWORD %L CREATEROLE NOCREATEDB NOSUPERUSER',
         :'mig_pw')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_migration')
\gexec

-- 2) 应用最小权限角色：非超级用户、不可建角色、不可建库
--    细粒度表级权限由 Alembic 迁移 NB-1 (e9a3b5c7d921) 授予
SELECT format(
         'CREATE ROLE mes_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEROLE NOCREATEDB',
         :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_app')
\gexec

-- 2b) 幂等：角色已存在时同步口令并重申属性边界（不放大权限）
SELECT format(
         'ALTER ROLE mes_app WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEROLE NOCREATEDB',
         :'app_pw')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_app')
\gexec

-- 3) 迁移角色接管数据库所有权，确保可创建 schema/表/序列 及 public 下的对象
ALTER DATABASE :"db" OWNER TO mes_migration;

-- 4) 允许两个角色连接数据库
GRANT CONNECT ON DATABASE :"db" TO mes_migration, mes_app;
EOSQL

echo "[initdb] mes_migration / mes_app roles ensured; database owner set to mes_migration."
