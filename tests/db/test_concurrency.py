"""F 组并发测试（数据库级）。

覆盖（任务书 F）：
- action_key 并发重复提交：(task_id, action_key) UNIQUE，并发仅一胜（NB-3）；
- client_token 重试：部分唯一索引，同 token 落第二行被拒（网络层幂等）；
- 库存扣减并发：CHECK 底线 weight_kg >= 0，并发超扣一成一败；
- reversal 并发：应用层"条件更新守卫"模式（UPDATE...WHERE is_effective RETURNING）；
- report_seq 并发：ref.code_rule 行锁推进，发号不重不漏（与 action_key 分工）。

发现（NB-P3-1，NON-BLOCKER）：aud.reversal_record 无 (original_ref_type, original_ref_id)
唯一约束，DB 层无法独立阻止重复冲正记录——依赖应用层守卫（本文件一并留证）。
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from conftest import connect, fails
from helpers import B, NOW


def _setup_task(conn):
    """最小生产链：返回 (team, ac, step, task)。"""
    b = B(conn)
    pid, sid = b.project()
    team = b.team()
    cli = b.list_item(sid)
    b.bom_line(cli)
    ac = b.component(sid, cli, "F1")
    step = b.route_step(pid)
    task = b.task(ac, step, team)
    return team, ac, step, task


def _run_two(worker):
    """两个线程同时起跑，返回 {名字: 结果}。"""
    barrier = threading.Barrier(2)
    results = {}

    def wrapped(name):
        c = connect("postgres")
        try:
            barrier.wait(timeout=10)
            results[name] = worker(c)
        except Exception as e:  # noqa: BLE001 — 线程内异常统一带回归断言
            c.rollback()
            results[name] = e
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(wrapped, ["a", "b"]))
    return results


# ============ F-1 action_key 并发重复提交 ============

def test_f1_action_key_concurrent_duplicate(conn):
    team, ac, step, task = _setup_task(conn)
    conn.commit()

    def worker(c):
        c.execute(
            "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
            "execute_team_id, channel, action_key, occurred_at) "
            "VALUES (%s, %s, %s, %s, 'scan', 'act-key-1', %s)",
            (task, ac, step, team, NOW))
        c.commit()
        return "ok"

    results = _run_two(worker)
    outcomes = sorted(v if isinstance(v, str) else type(v).__name__ for v in results.values())
    assert outcomes == ["UniqueViolation", "ok"], f"并发结果异常: {results}"
    n = conn.execute("SELECT count(*) FROM prod.production_report WHERE action_key='act-key-1'").fetchone()[0]
    assert n == 1, "(task_id, action_key) 唯一约束下只允许落一行"


# ============ F-2 client_token 网络重试 ============

def test_f2_client_token_retry_no_second_row(conn):
    team, ac, step, task = _setup_task(conn)
    conn.commit()

    c = connect("postgres")
    c.execute(
        "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
        "execute_team_id, channel, action_key, client_token, occurred_at) "
        "VALUES (%s, %s, %s, %s, 'scan', 'act-a', 'tk-retry-1', %s)",
        (task, ac, step, team, NOW))
    c.commit()
    c.close()

    # 网络超时重试：同 token（客户端可能换/不换 action_key）都不允许落第二行
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
          "execute_team_id, channel, action_key, client_token, occurred_at) "
          "VALUES (%s, %s, %s, %s, 'scan', 'act-b', 'tk-retry-1', %s)",
          (task, ac, step, team, NOW), frag="ix_production_report_client_token")

    # 不同 token + 同 action_key 也被业务动作唯一拦截
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
          "execute_team_id, channel, action_key, client_token, occurred_at) "
          "VALUES (%s, %s, %s, %s, 'scan', 'act-a', 'tk-retry-2', %s)",
          (task, ac, step, team, NOW), frag="uq_production_report_task_action_key")

    # report_seq 无唯一约束（显示序号，可重复）——职责分离验证
    conn.execute(
        "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
        "execute_team_id, channel, report_seq, client_token, occurred_at) "
        "VALUES (%s, %s, %s, %s, 'manual', 7, 'tk-seq-a', %s)",
        (task, ac, step, team, NOW))
    conn.execute(
        "INSERT INTO prod.production_report(task_id, actual_component_id, route_template_step_id, "
        "execute_team_id, channel, report_seq, client_token, occurred_at) "
        "VALUES (%s, %s, %s, %s, 'manual', 7, 'tk-seq-b', %s)",
        (task, ac, step, team, NOW))


# ============ F-3 库存扣减并发（防超扣/负库存）============

def test_f3_stock_deduction_concurrent_negative_blocked(conn):
    b = B(conn)
    m = b.material()
    sup = b.supplier()
    _, lid = b.wh_loc()
    bid = b.batch(m, sup, "H-F3")
    b.stock_in(bid, lid, 100.0)
    conn.commit()

    def worker(c):
        c.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg - 60 "
                  "WHERE material_batch_id = %s AND storage_location_id = %s", (bid, lid))
        c.commit()
        return "ok"

    results = _run_two(worker)
    outcomes = sorted(v if isinstance(v, str) else type(v).__name__ for v in results.values())
    assert outcomes == ["CheckViolation", "ok"], f"并发扣减结果异常: {results}"
    assert b.balance(bid, lid) == pytest.approx(40.0), "并发超扣必须被 CHECK 底线拦下"


# ============ F-4 reversal 并发（应用层守卫模式）============

def _setup_consumption(conn):
    """入库 100 → 领料 50 → 直接消耗 20；返回 (b, bid, lid, cid, cons_row_id)。"""
    b = B(conn)
    pid, sid = b.project()
    m = b.material()
    sup = b.supplier()
    user = b.user()
    team = b.team()
    _, lid = b.wh_loc()
    bid = b.batch(m, sup, "H-F4")
    b.stock_in(bid, lid, 100.0)
    doc = b.issue_doc(user, team, sid)
    line = b.issue_line(doc, 1, m, bid, lid, 50)
    b.post_issue(line, 50, bid, lid)
    cli = b.list_item(sid)
    bl = b.bom_line(cli)
    ac = b.component(sid, cli, "F4")
    part = b.part(ac, bl)
    cid = b.consumption(part, bid, 20.0)
    row_id = conn.execute(
        "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
        "qty_weight, consumption_id, occurred_at) VALUES ('issue', %s, %s, 20, %s, %s) RETURNING id",
        (bid, lid, cid, NOW)).fetchone()[0]
    conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg - 20 "
                 "WHERE material_batch_id=%s AND storage_location_id=%s", (bid, lid))
    return b, bid, lid, cid, row_id


def test_f4_reversal_concurrent_guard_pattern(conn):
    """两线程同时冲正同一消耗：守卫（UPDATE...WHERE is_effective）保证仅一胜、单份反向账。"""
    b, bid, lid, cid, cons_row = _setup_consumption(conn)
    conn.commit()

    def worker(c):
        # T-10 要求冲正记录先于 is_effective 翻转落库；
        # 并发守卫：先 SELECT...FOR UPDATE 抢行锁并复验 is_effective，败者不写任何数据。
        c.execute("SELECT set_config('mes.reversal_context', 'on', true)")
        locked = c.execute("SELECT id FROM whs.material_consumption WHERE id=%s AND is_effective FOR UPDATE",
                           (cid,)).fetchone()
        if locked is None:
            c.commit()
            return "lost"
        c.execute("INSERT INTO aud.reversal_record(original_ref_type, original_ref_id, occurred_at) "
                  "VALUES ('material_consumption', %s, %s)", (cid, NOW))
        c.execute("UPDATE whs.material_consumption SET is_effective = false WHERE id = %s", (cid,))
        c.execute("INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
                  "qty_weight, correction_of_id, occurred_at) VALUES ('issue', %s, %s, -20, %s, %s)",
                  (bid, lid, cons_row, NOW))
        c.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg + 20 "
                  "WHERE material_batch_id=%s AND storage_location_id=%s", (bid, lid))
        c.commit()
        return "won"

    results = _run_two(worker)
    outcomes = sorted(v if isinstance(v, str) else type(v).__name__ for v in results.values())
    assert outcomes == ["lost", "won"], f"守卫模式应恰有一胜: {results}"

    n_rev = conn.execute("SELECT count(*) FROM aud.reversal_record "
                         "WHERE original_ref_type='material_consumption' AND original_ref_id=%s", (cid,)).fetchone()[0]
    n_ledger = conn.execute("SELECT count(*) FROM whs.stock_ledger WHERE correction_of_id=%s", (cons_row,)).fetchone()[0]
    assert n_rev == 1 and n_ledger == 1, "并发冲正只允许一份冲正记录+一份反向账行"
    assert b.balance(bid, lid) == pytest.approx(50.0), "100-50-20+20=50（冲正回补）"


def test_f4b_duplicate_reversal_record_not_db_blocked(conn):
    """NB-P3-1 留证：无守卫时 DB 不拦重复冲正记录（应用层契约义务）。"""
    _, _, _, cid, _ = _setup_consumption(conn)
    conn.execute("SELECT set_config('mes.reversal_context', 'on', true)")
    # 第一次冲正（正常路径：先记录后翻转）
    conn.execute("INSERT INTO aud.reversal_record(original_ref_type, original_ref_id, occurred_at) "
                 "VALUES ('material_consumption', %s, %s)", (cid, NOW))
    conn.execute("UPDATE whs.material_consumption SET is_effective=false WHERE id=%s", (cid,))
    # 第二次冲正记录可落库 —— DB 无 (original_ref_type, original_ref_id) 唯一约束
    conn.execute("INSERT INTO aud.reversal_record(original_ref_type, original_ref_id, occurred_at) "
                 "VALUES ('material_consumption', %s, %s)", (cid, NOW))
    n = conn.execute("SELECT count(*) FROM aud.reversal_record "
                     "WHERE original_ref_type='material_consumption' AND original_ref_id=%s", (cid,)).fetchone()[0]
    assert n == 2, "本测试用于固化 NON-BLOCKER 证据：重复冲正记录依赖应用层守卫拦截"


# ============ F-5 report_seq 并发发号（code_rule 行锁）============

def test_f5_report_seq_concurrent_distinct(conn):
    key = f"test_seq_{uuid4().hex[:10]}"
    conn.execute("INSERT INTO ref.code_rule(rule_key, prefix, seq_current, seq_padding, reset_policy) "
                 "VALUES (%s, 'R', 0, 4, 'never')", (key,))
    conn.commit()

    def worker(c):
        cur = c.execute("UPDATE ref.code_rule SET seq_current = seq_current + 1 "
                        "WHERE rule_key = %s RETURNING seq_current", (key,))
        got = cur.fetchone()[0]
        c.commit()
        return got

    results = _run_two(worker)
    vals = sorted(v if not isinstance(v, Exception) else str(v) for v in results.values())
    assert vals == [1, 2], f"行锁发号必须不重不漏: {results}"
    final = conn.execute("SELECT seq_current FROM ref.code_rule WHERE rule_key=%s", (key,)).fetchone()[0]
    assert final == 2
    # 自清理：ref 不参与 TRUNCATE，测试行用后即删
    conn.execute("DELETE FROM ref.code_rule WHERE rule_key=%s", (key,))
    conn.commit()
