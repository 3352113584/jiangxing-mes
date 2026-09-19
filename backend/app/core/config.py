"""Phase 4 Sprint 1 — 应用层配置。

所有配置来自环境变量，默认值对齐本地测试库（tests/db/conftest.py 约定：
jiangxing_mes_test @ localhost:15432，应用角色 mes_app，trust 登录）。
生产环境通过环境变量覆盖，不在此硬编码任何密码/Token。
"""
from __future__ import annotations

import os

from app.db.db_url_resolver import resolve_app_db_url, resolve_migration_db_url


class Settings:
    # 应用连接使用 mes_app 角色（权限矩阵：SELECT+INSERT 全表，UPDATE 仅 81 表，DELETE=0）。
    DATABASE_URL: str = resolve_app_db_url()
    # 数据库迁移（DDL）使用超级用户 postgres。变量名与 Alembic env.py 保持一致。
    MIGRATION_DATABASE_URL: str = resolve_migration_db_url()
    # Token 签名密钥（生产必须覆盖）。
    SECRET: str = os.getenv("MES_SECRET", "dev-secret-change-me-in-prod")
    # Token 有效期（秒），默认 12 小时。
    TOKEN_TTL: int = int(os.getenv("MES_TOKEN_TTL", "43200"))
    # 是否处于演示/开发模式（影响一些宽松校验，以及 CORS 是否允许通配）。
    DEBUG: bool = os.getenv("MES_DEBUG", "false").lower() in ("1", "true", "yes")
    # 时区（应用层显示/日志用；数据库 CURRENT_DATE 由 PostgreSQL 实例时区决定，须 Asia/Shanghai）。
    TZ: str = os.getenv("TZ", "Asia/Shanghai")


settings = Settings()
