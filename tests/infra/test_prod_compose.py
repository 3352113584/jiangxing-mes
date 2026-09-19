"""验证生产 docker-compose 配置：隔离、端口、网络关系、时区。

不依赖 docker 运行时，仅静态解析 YAML 文件。
运行方式（仓库根目录）：
  PYTHONPATH=backend python -m pytest tests/infra/test_prod_compose.py -p no:cacheprovider -q
"""
from __future__ import annotations

import os

import yaml

COMPOSE_PATH = os.path.join("deploy", "docker-compose.prod.yml")


def _load():
    with open(COMPOSE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_compose_parseable():
    data = _load()
    assert "services" in data
    assert {"postgres", "backend", "gateway"} <= set(data["services"].keys())


def test_postgres_not_exposed_publicly():
    data = _load()
    pg = data["services"]["postgres"]
    # 关键：生产 PostgreSQL 不得映射任何公网/宿主机端口
    assert "ports" not in pg, "postgres 不应暴露端口到宿主机/公网"


def test_backend_not_exposed_publicly():
    data = _load()
    be = data["services"]["backend"]
    assert "ports" not in be, "backend 不应直接暴露公网，仅由网关在内部网络访问"


def test_gateway_publishes_only_http_https():
    data = _load()
    gw = data["services"]["gateway"]
    ports = gw.get("ports", [])
    published = " ".join(ports)
    assert "5432" not in published, "网关不得暴露数据库端口"
    assert "8000" not in published, "网关不得将后端端口直接暴露公网"
    assert any("443" in p for p in ports), "必须发布 HTTPS 443"
    assert any("80" in p for p in ports), "应发布 80 用于跳转（可选）"


def test_network_isolation():
    data = _load()
    services = data["services"]
    net = "mes_net"
    for name in ("postgres", "backend", "gateway"):
        assert net in services[name].get("networks", []), (
            f"{name} 必须位于内部网络 {net}"
        )
    assert services["postgres"]["networks"] == [net]
    assert net in data.get("networks", {})


def test_backend_uses_internal_postgres_hostname():
    data = _load()
    be = data["services"]["backend"]
    db_url = be["environment"]["MES_DATABASE_URL"]
    assert "@postgres:5432" in db_url, "后端必须通过内部服务名 postgres 连接数据库"


def test_migration_uses_same_internal_hostname():
    data = _load()
    be = data["services"]["backend"]
    mig_url = be["environment"]["MES_MIGRATION_DATABASE_URL"]
    assert "@postgres:5432" in mig_url, "迁移连接也必须使用内部服务名 postgres"


def test_gateway_depends_on_backend():
    data = _load()
    gw = data["services"]["gateway"]
    assert "backend" in gw.get("depends_on", [])


def test_timezone_configured():
    data = _load()
    pg_env = data["services"]["postgres"]["environment"]
    assert pg_env.get("TZ") == "Asia/Shanghai"
    assert pg_env.get("PGTZ") == "Asia/Shanghai"
    assert "timezone=Asia/Shanghai" in pg_env.get("POSTGRES_INITDB_ARGS", "")
    assert data["services"]["backend"]["environment"].get("TZ") == "Asia/Shanghai"


def test_secrets_not_hardcoded_in_compose():
    data = _load()
    raw = yaml.dump(data)
    # 不得出现任何硬编码的密码/密钥明文
    assert "CHANGEME" not in raw
    assert "password" not in raw.lower() or "${POSTGRES_PASSWORD}" in raw
    # 密码必须通过环境变量注入
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD" in raw
    assert "${MES_SECRET:?MES_SECRET" in raw
