"""部署基础设施测试：CORS 与数据库 URL 变量命名。

不依赖真实数据库；仅验证应用层配置与中间件行为。
运行方式（仓库根目录）：
  PYTHONPATH=backend python -m pytest tests/infra/test_cors_and_config.py -p no:cacheprovider -q
"""
from __future__ import annotations

import importlib
import os

from fastapi.testclient import TestClient


def _build_app(cors_origins: str = "", debug: str = "false"):
    os.environ["MES_CORS_ORIGINS"] = cors_origins
    os.environ["MES_DEBUG"] = debug
    import app.main as main_mod

    importlib.reload(main_mod)
    return main_mod.app


def test_prod_accepts_configured_origin_and_rejects_others():
    app = _build_app(cors_origins="https://mes.example.com", debug="false")
    client = TestClient(app)
    # 已配置的来源应通过预检
    r = client.options(
        "/health",
        headers={
            "Origin": "https://mes.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://mes.example.com"
    # 任意来源必须被拒绝（不返回匹配的 ACAO 头）
    r2 = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in r2.headers
    # 普通 GET 带任意 Origin 也不应带 ACAO
    r3 = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r3.headers


def test_prod_default_rejects_all_cross_origin():
    # 生产未配置 MES_CORS_ORIGINS 且非 debug → 拒绝所有跨域
    app = _build_app(cors_origins="", debug="false")
    client = TestClient(app)
    r = client.options(
        "/health",
        headers={
            "Origin": "https://anything.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in r.headers


def test_dev_allows_wildcard_but_no_credentials():
    # 开发模式（MES_DEBUG=true）保留通配，便于本地调试
    app = _build_app(cors_origins="", debug="true")
    client = TestClient(app)
    r = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "*"
    # 通配时不允许携带凭据（避免非法 CORS 组合）
    assert r.headers.get("access-control-allow-credentials") != "true"


def test_config_has_canonical_db_url_attributes():
    from app.core.config import settings

    # 应用与迁移必须使用各自的独立变量（最小权限原则）
    assert hasattr(settings, "DATABASE_URL")
    assert hasattr(settings, "MIGRATION_DATABASE_URL")
    assert "MES_DATABASE_URL" in os.environ or isinstance(settings.DATABASE_URL, str)
    assert isinstance(settings.MIGRATION_DATABASE_URL, str)


def test_resolver_reads_canonical_migration_var(monkeypatch):
    import app.db.db_url_resolver as resolver

    monkeypatch.setenv("MES_MIGRATION_DATABASE_URL", "postgresql+psycopg://pg@db:5432/prod")
    monkeypatch.delenv("MES_DB_URL", raising=False)
    importlib.reload(resolver)
    assert resolver.resolve_migration_db_url() == "postgresql+psycopg://pg@db:5432/prod"


def test_resolver_falls_back_to_legacy_mes_db_url(monkeypatch):
    import app.db.db_url_resolver as resolver

    monkeypatch.delenv("MES_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("MES_DB_URL", "postgresql+psycopg://legacy@db:5432/prod")
    importlib.reload(resolver)
    assert resolver.resolve_migration_db_url() == "postgresql+psycopg://legacy@db:5432/prod"


def test_env_py_uses_canonical_migration_var():
    # Alembic env.py 必须与 config.py 使用同一迁移变量名（B-3）
    env_py = os.path.join("backend", "migrations", "env.py")
    with open(env_py, encoding="utf-8") as f:
        content = f.read()
    assert "MES_MIGRATION_DATABASE_URL" in content
