"""验证生产 docker-compose 配置：隔离、端口、网络关系、时区。

不依赖 docker 运行时，仅静态解析 YAML 文件。
运行方式（仓库根目录）：
  PYTHONPATH=backend python -m pytest tests/infra/test_prod_compose.py -p no:cacheprovider -q
"""
from __future__ import annotations

import os
import re

import yaml

COMPOSE_PATH = os.path.join("deploy", "docker-compose.prod.yml")
GATEWAY_PATH = os.path.join("deploy", "nginx", "gateway.conf")
INITDB_PATH = os.path.join("deploy", "docker", "initdb", "01_create_roles.sh")
ENTRYPOINT_PATH = os.path.join("backend", "docker-entrypoint.sh")
GITATTRIBUTES_PATH = ".gitattributes"


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
    """时区必须为 Asia/Shanghai，但【不得】通过 initdb 参数设置。

    F1 修复说明：initdb 没有 --timezone 选项，传该参数会导致
    `initdb: unrecognized option: timezone=Asia/Shanghai`，
    PostgreSQL 无法初始化、容器进入 Restarting。
    正确做法是只设置 TZ / PGTZ 环境变量（initdb 阶段即读取 TZ）。
    实机已验证：仅设 TZ 时 SHOW timezone 返回 Asia/Shanghai。
    """
    data = _load()
    pg_env = data["services"]["postgres"]["environment"]
    assert pg_env.get("TZ") == "Asia/Shanghai"
    assert pg_env.get("PGTZ") == "Asia/Shanghai"

    initdb_args = pg_env.get("POSTGRES_INITDB_ARGS", "")
    assert "--timezone" not in initdb_args, (
        "POSTGRES_INITDB_ARGS 不得包含 --timezone（initdb 无该选项，会导致初始化失败）"
    )
    assert "timezone=Asia/Shanghai" not in initdb_args
    # 编码与 locale 仍应显式指定
    assert "--encoding=UTF8" in initdb_args
    assert "--locale=C.UTF-8" in initdb_args

    assert data["services"]["backend"]["environment"].get("TZ") == "Asia/Shanghai"


# ---------------------------------------------------------------------------
# F3 / F4 / F2 / F5 回归防护（对应 Staging 实机验证发现的部署层缺陷）
# ---------------------------------------------------------------------------
def test_initdb_script_has_no_psql_var_inside_dollar_quote():
    """F3：美元引用块（DO $$ ... $$）内不得使用 psql 变量语法 :'var'。

    美元引用块对 psql 不透明、不会插值，语句原样送交服务端后报
    `ERROR: syntax error at or near ":"`，导致 mes_migration / mes_app
    从未被创建、账号分离在生产实际失效。
    """
    text = open(INITDB_PATH, encoding="utf-8").read()
    for m in re.finditer(r"\$\$(.*?)\$\$", text, re.S):
        body = m.group(1)
        assert not re.search(r":'", body), (
            "DO $$ ... $$ 内不得使用 :'var'（psql 不会在美元引用块内插值）"
        )
        assert not re.search(r':"', body), (
            'DO $$ ... $$ 内不得使用 :"var"（psql 不会在美元引用块内插值）'
        )


def test_initdb_script_uses_format_gexec_and_correct_role_attributes():
    """F3：角色必须用 format(%L) + \\gexec 创建，且属性不可放宽。"""
    text = open(INITDB_PATH, encoding="utf-8").read()
    assert "format(" in text, "应使用 format(%L) 生成安全引用的 SQL 文本"
    assert "\\gexec" in text, "应使用 \\gexec 执行 format 生成的语句"

    # 迁移角色：NOSUPERUSER + CREATEROLE + NOCREATEDB
    assert "mes_migration" in text
    assert "CREATEROLE NOCREATEDB NOSUPERUSER" in text, (
        "mes_migration 必须为 NOSUPERUSER + CREATEROLE + NOCREATEDB"
    )
    # 应用角色：NOSUPERUSER + NOCREATEROLE + NOCREATEDB
    assert "mes_app" in text
    assert "NOSUPERUSER NOCREATEROLE NOCREATEDB" in text, (
        "mes_app 必须为 NOSUPERUSER + NOCREATEROLE + NOCREATEDB"
    )
    # 数据库归属与连接权限
    assert "ALTER DATABASE" in text and "OWNER TO mes_migration" in text
    assert "GRANT CONNECT ON DATABASE" in text
    # 口令缺失时必须立即失败，避免建出空口令账号
    assert "MES_MIGRATION_PASSWORD:?" in text
    assert "MES_APP_PASSWORD:?" in text


def test_gateway_log_format_name_does_not_conflict_with_nginx_default():
    """F4：log_format 不得命名为 main（nginx.conf 已定义 main）。

    否则 nginx 启动报 `[emerg] duplicate "log_format" name "main"`，网关无法启动。
    同时确认 HTTPS / TLS1.2+1.3 / HSTS 等安全要求未被削弱。
    """
    text = open(GATEWAY_PATH, encoding="utf-8").read()
    names = re.findall(r"^\s*log_format\s+([A-Za-z0-9_]+)\s", text, re.M)
    assert names, "gateway.conf 应定义自定义 access log 格式"
    assert "main" not in names, (
        'log_format 不得命名为 "main"（与 nginx.conf 冲突，会导致 nginx 无法启动）'
    )
    assert len(names) == len(set(names)), f"log_format 定义重复: {names}"
    for n in set(names):
        assert f"access_log /var/log/nginx/access.log {n};" in text, (
            f"access_log 必须显式引用已定义格式 {n}"
        )

    # 安全要求不得被削弱
    assert "listen 443 ssl;" in text
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in text
    assert "Strict-Transport-Security" in text
    assert "X-Content-Type-Options" in text
    assert "X-Frame-Options" in text


def test_shell_entrypoints_are_lf():
    """F2/F5：shell 脚本必须为 LF 且以 #!/bin/sh 开头，才能在 Linux 容器内直接执行。

    CRLF 会让内核把 shebang 读成 `#!/bin/sh\\r`，报
    `/bin/sh^M: bad interpreter: No such file or directory`。
    """
    for path in (INITDB_PATH, ENTRYPOINT_PATH):
        raw = open(path, "rb").read()
        assert b"\r\n" not in raw, f"{path} 含 CRLF，Linux 下无法执行"
        assert b"\r" not in raw, f"{path} 含裸 CR，Linux 下无法执行"
        assert raw.startswith(b"#!/bin/sh\n"), f"{path} 必须以 #!/bin/sh 开头并为 LF"


def test_gitattributes_forces_lf():
    """.gitattributes 必须强制文本文件为 LF，避免开发机 core.autocrlf 污染归档。"""
    text = open(GITATTRIBUTES_PATH, encoding="utf-8").read()
    assert "text=auto eol=lf" in text, "应设置 * text=auto eol=lf"
    for pattern in ("*.sh", "*.py", "*.sql", "*.yml", "*.conf", "Dockerfile"):
        assert pattern in text, f".gitattributes 应显式声明 {pattern} 为 LF"
    # 二进制类型不得被转换
    for pattern in ("*.png", "*.xlsx", "*.apk"):
        assert pattern in text, f".gitattributes 应声明 {pattern} 为 binary"


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
