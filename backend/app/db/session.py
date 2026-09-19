"""Phase 4 Sprint 1 — SQLAlchemy 引擎与会话（应用运行态，使用 mes_app 角色）。

迁移（DDL）使用 MIGRATION_DATABASE_URL（postgres），由 Alembic 调用，不在应用运行态使用。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# 生产连接池：避免云数据库连接因空闲被中间件断开（pool_recycle），
# 并通过 pre_ping 检测失效连接。参数可由环境变量覆盖。
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("MES_DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("MES_DB_MAX_OVERFLOW", "20")),
    pool_recycle=int(os.getenv("MES_DB_POOL_RECYCLE", "1800")),
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
