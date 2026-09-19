"""Phase 4 Sprint 1 — 应用层配置。

所有配置来自环境变量，默认值对齐本地测试库（tests/db/conftest.py 约定：
jiangxing_mes_test @ localhost:15432，应用角色 mes_app，trust 登录）。
生产环境通过环境变量覆盖，不在此硬编码任何密码/Token。
"""
from __future__ import annotations

import os


class Settings:
    # 应用连接使用 mes_app 角色（权限矩阵：SELECT+INSERT 全表，UPDATE 仅 81 表，DELETE=0）。
    DATABASE_URL: str = os.getenv(
        "MES_DATABASE_URL",
        "postgresql+psycopg://mes_app@localhost:15432/jiangxing_mes_test",
    )
    # 数据库迁移（DDL）使用超级用户 postgres。
    MIGRATION_DATABASE_URL: str = os.getenv(
        "MES_MIGRATION_DATABASE_URL",
        "postgresql+psycopg://postgres@localhost:15432/jiangxing_mes_test",
    )
    # Token 签名密钥（生产必须覆盖）。
    SECRET: str = os.getenv("MES_SECRET", "dev-secret-change-me-in-prod")
    # Token 有效期（秒），默认 12 小时。
    TOKEN_TTL: int = int(os.getenv("MES_TOKEN_TTL", "43200"))
    # 是否处于演示/开发模式（影响一些宽松校验）。
    DEBUG: bool = os.getenv("MES_DEBUG", "false").lower() in ("1", "true", "yes")


settings = Settings()
