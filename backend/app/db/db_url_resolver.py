"""DB URL 解析（应用运行态与 Alembic 迁移共用，统一变量命名）。

生产环境必须使用以下两个独立变量（不同数据库角色，最小权限原则）：
- MES_DATABASE_URL          : 应用运行态连接（最小权限角色，如 mes_app）
- MES_MIGRATION_DATABASE_URL: DDL/迁移连接（超级用户角色，如 postgres）

历史遗留变量 MES_DB_URL 仅作为迁移 URL 的兼容回退，不推荐继续使用。

注意：本模块只解析环境变量，不建立任何连接、不修改任何业务规则。
"""
from __future__ import annotations

import os

# 本地测试库默认（仅当未设置任何环境变量时；生产必须由环境变量覆盖）。
DEFAULT_APP_URL = "postgresql+psycopg://mes_app@localhost:15432/jiangxing_mes_test"
DEFAULT_MIGRATION_URL = "postgresql+psycopg://postgres@localhost:15432/jiangxing_mes_test"


def resolve_app_db_url() -> str:
    """应用运行态数据库连接串（最小权限角色）。"""
    return os.environ.get("MES_DATABASE_URL", DEFAULT_APP_URL)


def resolve_migration_db_url() -> str:
    """迁移/DDL 数据库连接串（超级用户角色）。

    优先 MES_MIGRATION_DATABASE_URL；兼容旧变量 MES_DB_URL；最后回退默认。
    """
    return (
        os.environ.get("MES_MIGRATION_DATABASE_URL")
        or os.environ.get("MES_DB_URL")
        or DEFAULT_MIGRATION_URL
    )
