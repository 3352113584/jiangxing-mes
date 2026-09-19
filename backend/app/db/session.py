"""Phase 4 Sprint 1 — SQLAlchemy 引擎与会话（应用运行态，使用 mes_app 角色）。

迁移（DDL）使用 MIGRATION_DATABASE_URL（postgres），由 Alembic 调用，不在应用运行态使用。
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
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
