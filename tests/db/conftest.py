"""Phase 3 数据库级测试夹具（jiangxing_mes_test @ PG16 便携版 :15432）。

约定：
- ref schema（C 类字典）测试间不清空，仅读取；
- 其余 7 schema 每个测试前 TRUNCATE CASCADE；
- conn=postgres 管理连接；app_conn=mes_app 应用角色连接（权限矩阵验证用）。
"""
import os

import psycopg
import pytest

DB = dict(host="localhost", port=int(os.environ.get("MES_PG_PORT", "15432")),
          dbname=os.environ.get("MES_TEST_DB", "jiangxing_mes_test"))
ALL_SCHEMAS = ["ref", "md", "eng", "imp", "prod", "whs", "ship", "aud"]
TRUNCATE_SCHEMAS = ["md", "eng", "imp", "prod", "whs", "ship", "aud"]


def connect(user: str) -> psycopg.Connection:
    return psycopg.connect(**DB, user=user)


def truncate_business(conn: psycopg.Connection) -> None:
    old = conn.autocommit
    conn.autocommit = True
    tables = conn.execute(
        "SELECT string_agg(format('%%I.%%I', n.nspname, c.relname), ', ' ORDER BY c.relname) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' AND n.nspname = ANY(%s) "
        "AND NOT (n.nspname = 'md' AND c.relname = 'role')", (TRUNCATE_SCHEMAS,)
    ).fetchone()[0]
    conn.execute(f"TRUNCATE TABLE {tables} CASCADE")
    conn.autocommit = old


@pytest.fixture(scope="session", autouse=True)
def ensure_role_seed():
    """md.role 种子行保障（测试库重建后仍可用；role_code 唯一幂等）。"""
    roles = [("admin", "系统管理员"), ("warehouse_keeper", "仓管员"),
             ("production_dispatcher", "生产调度"), ("worker", "作业工人"),
             ("quality_inspector", "质检员"), ("planner", "计划员"),
             ("sales", "销售"), ("finance", "财务"), ("viewer", "只读查看")]
    c = connect("postgres")
    with c.cursor() as cur:
        cur.executemany(
            "INSERT INTO md.role(role_code, name, is_system) VALUES (%s, %s, true) "
            "ON CONFLICT (role_code) DO NOTHING", roles)
    c.commit()
    c.close()
    yield


@pytest.fixture()
def conn() -> psycopg.Connection:
    """管理连接（postgres），每个测试前清空业务表。"""
    c = connect("postgres")
    truncate_business(c)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture()
def app_conn(conn) -> psycopg.Connection:
    """应用角色连接（mes_app），依赖 conn 先完成清空。"""
    c = connect("mes_app")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def fails(conn, exc, sql, params=None, frag=""):
    """断言 SQL 失败且错误消息含 frag；SAVEPOINT 回滚，不影响外层事务中的 setup 数据。"""
    try:
        with conn.transaction():
            conn.execute(sql, params or ())
    except exc as e:
        assert frag in str(e), f"期望错误含 [{frag}]，实际 [{e}]"
        return
    raise AssertionError(f"应当失败但成功: {sql}")


def succeeds(conn, sql, params=None):
    """断言 SQL 成功（不提交，保持与 setup 同事务；需要跨连接可见时测试内显式 commit）。"""
    conn.execute(sql, params or ())
