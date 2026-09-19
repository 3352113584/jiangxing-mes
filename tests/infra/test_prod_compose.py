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


def _db_url_role(url: str) -> str | None:
    """Extract the role/user segment from a postgresql[+psycopg]://user:pass@host URL."""
    import re

    m = re.search(r"//([^:@/]+):", url)
    return m.group(1) if m else None


def test_app_db_url_uses_least_privilege_role():
    """B1：应用连接必须使用最小权限角色 mes_app，不得复用镜像管理员账号。"""
    data = _load()
    be = data["services"]["backend"]
    db_url = be["environment"]["MES_DATABASE_URL"]
    assert "/mes_app:" in db_url, "MES_DATABASE_URL 必须使用最小权限角色 mes_app"
    assert "mes_user" not in db_url, "MES_DATABASE_URL 不得指向管理员 mes_user"
    assert "${POSTGRES_USER" not in db_url, "MES_DATABASE_URL 不得指向 POSTGRES_USER 管理员账号"


def test_migration_db_url_uses_separate_migration_role():
    """B1：迁移连接必须使用独立迁移角色 mes_migration，与应用角色严格分离。"""
    data = _load()
    be = data["services"]["backend"]
    mig_url = be["environment"]["MES_MIGRATION_DATABASE_URL"]
    assert "/mes_migration:" in mig_url, "MES_MIGRATION_DATABASE_URL 必须使用迁移角色 mes_migration"
    assert "mes_user" not in mig_url, "MES_MIGRATION_DATABASE_URL 不得指向管理员 mes_user"
    assert "${POSTGRES_USER" not in mig_url, "MES_MIGRATION_DATABASE_URL 不得指向 POSTGRES_USER 管理员账号"
    # 应用角色与迁移角色必须不同
    db_url = be["environment"]["MES_DATABASE_URL"]
    assert _db_url_role(db_url) != _db_url_role(mig_url), "应用角色与迁移角色必须分离"


def test_postgres_mounts_initdb_for_role_creation():
    """B1：postgres 必须挂载 initdb 目录，以在首次初始化时创建 mes_migration/mes_app。"""
    data = _load()
    pg = data["services"]["postgres"]
    vols = " ".join(pg.get("volumes", []))
    assert "docker-entrypoint-initdb.d" in vols, (
        "postgres 必须挂载 initdb 目录（deploy/docker/initdb），"
        "否则 mes_migration/mes_app 角色不会被创建"
    )


def test_postgres_exposes_role_passwords_to_initdb():
    """B1：postgres 必须向 initdb 脚本暴露两个角色口令，供账号分离使用。"""
    data = _load()
    pg_env = data["services"]["postgres"]["environment"]
    assert "MES_APP_PASSWORD" in pg_env, "postgres 必须向 initdb 暴露 MES_APP_PASSWORD"
    assert "MES_MIGRATION_PASSWORD" in pg_env, "postgres 必须向 initdb 暴露 MES_MIGRATION_PASSWORD"


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
    # 任何出现 password 字样的，必须是 ${...} 环境变量引用（不允许硬编码明文）
    assert "password" not in raw.lower() or any(
        f"${{{v}}}" in raw
        for v in ("POSTGRES_PASSWORD", "MES_APP_PASSWORD", "MES_MIGRATION_PASSWORD")
    ), "密码必须以环境变量（${...}）注入，不得硬编码明文"
    # 密码必须通过环境变量注入
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD" in raw
    assert "${MES_APP_PASSWORD:?MES_APP_PASSWORD" in raw
    assert "${MES_MIGRATION_PASSWORD:?MES_MIGRATION_PASSWORD" in raw
    assert "${MES_SECRET:?MES_SECRET" in raw
