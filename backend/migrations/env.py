"""Alembic environment for MES V1.2 (Phase 3).

- target_metadata = app.db.base.Base.metadata (131 tables, 8 schemas).
- include_schemas=True: all objects live under ref/md/eng/imp/prod/whs/ship/aud.
- DB URL from MES_DB_URL env var; default = local dev database.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the backend package importable when alembic runs from any cwd.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  (register all tables)
from app.db.db_url_resolver import resolve_migration_db_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 迁移连接串统一使用 MES_MIGRATION_DATABASE_URL（与 config.py 一致），
# 兼容旧变量 MES_DB_URL；默认回退到本地开发库。
DEFAULT_URL = "postgresql+psycopg://postgres@localhost:15432/jiangxing_mes"
db_url = resolve_migration_db_url()
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata

# Schemas owned by the MES model (excluded from autogenerate diff).
MODEL_SCHEMAS = {"ref", "md", "eng", "imp", "prod", "whs", "ship", "aud"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return obj.schema in MODEL_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        version_table_schema="public",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            compare_type=True,
            version_table_schema="public",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
