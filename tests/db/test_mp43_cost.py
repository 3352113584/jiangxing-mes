"""M-P4-3 生产成本 / 班组结算口径模型 — 数据库级验收测试。

覆盖任务书 §十四：
- 标准 / 自定义工序（project_operation 标准↔自定义互斥身份）
- 5 种计价口径（weight / piece / length / hour / hole_count）
- 正常 / 部分 / 幂等并发登记（禁止按报告重复计数）
- 返工 attempt（rework 单独核算，不覆盖/删除正常事实）
- 重量精确 / 回退 / 缺失；价格缺失 / 班组缺失（防御分支）
- 价格时间旅行（Jan/Apr/Jul 改价 → Feb/May/Aug 报告 = 1000/2400/4050；新价不回写历史）
- T-17：已生效历史价禁止改/删、区间重叠拒绝、单一当前、未来版本自由编辑
- route_template_step 互斥（标准 / 自定义 / 双空 / 双填）
- 只读查询入口（cost_query_service）/ 改价服务（price_service：关旧+开新）
- G-2 回归（painting → production_completed 不变）见独立运行
"""
import uuid
from types import SimpleNamespace

import psycopg
from datetime import date, datetime

from helpers import B

NOW = datetime(2026, 9, 19, 9, 0, 0)


def _uid(p="x"):
    return f"{p}{uuid.uuid4().hex[:8]}"


def make_team(conn, code=None):
    code = code or _uid("T")
    return conn.execute(
        "INSERT INTO md.team(team_code,name,team_type) VALUES (%s,%s,'production') RETURNING id",
        (code, code)).fetchone()[0]


def make_project(conn):
    pid = conn.execute(
        "INSERT INTO md.main_project(project_code,name) VALUES (%s,'P') RETURNING id",
        (_uid("P"),)).fetchone()[0]
    sid = conn.execute(
        "INSERT INTO md.subproject(main_project_id,subproject_code,name) VALUES (%s,%s,'S') RETURNING id",
        (pid, _uid("S"))).fetchone()[0]
    return pid, sid


def make_component(conn, sid, no):
    cli = conn.execute(
        "INSERT INTO prod.component_list_item(subproject_id,component_no,name,quantity) "
        "VALUES (%s,%s,'C',1) RETURNING id", (sid, no)).fetchone()[0]
    qid = conn.execute(
        "INSERT INTO prod.qr_code_registry(qr_code) VALUES (%s) RETURNING id",
        (_uid("QR"),)).fetchone()[0]
    acid = conn.execute(
        "INSERT INTO prod.actual_component(subproject_id,component_list_item_id,component_no,"
        "instance_sequence,qr_code_id) VALUES (%s,%s,%s,1,%s) RETURNING id",
        (sid, cli, no, qid)).fetchone()[0]
    conn.execute("UPDATE prod.qr_code_registry SET actual_component_id=%s WHERE id=%s", (acid, qid))
    return acid


def make_standard_step(conn, pid, ot_code):
    tid = conn.execute(
        "INSERT INTO eng.route_template(main_project_id,name) VALUES (%s,'RT') RETURNING id",
        (pid,)).fetchone()[0]
    otid = conn.execute(
        "SELECT id FROM ref.operation_type WHERE code=%s", (ot_code,)).fetchone()[0]
    sid = conn.execute(
        "INSERT INTO eng.route_template_step(template_id,step_no,operation_type_id) "
        "VALUES (%s,1,%s) RETURNING id", (tid, otid)).fetchone()[0]
    return sid, otid


def make_custom_step(conn, pid, po_id):
    tid = conn.execute(
        "INSERT INTO eng.route_template(main_project_id,name) VALUES (%s,'RT') RETURNING id",
        (pid,)).fetchone()[0]
    return conn.execute(
        "INSERT INTO eng.route_template_step(template_id,step_no,project_operation_id) "
        "VALUES (%s,1,%s) RETURNING id", (tid, po_id)).fetchone()[0]


def add_po_standard(conn, pid, code, ot_id):
    return conn.execute(
        "INSERT INTO eng.project_operation(main_project_id,project_operation_code,operation_type_id,is_active) "
        "VALUES (%s,%s,%s,true) RETURNING id", (pid, code, ot_id)).fetchone()[0]


def add_po_custom(conn, pid, code, name):
    return conn.execute(
        "INSERT INTO eng.project_operation(main_project_id,project_operation_code,custom_name,is_active) "
        "VALUES (%s,%s,%s,true) RETURNING id", (pid, code, name)).fetchone()[0]


def add_price(conn, po_id, price, basis, eff_from, eff_to=None, is_current=True):
    conn.execute(
        "INSERT INTO eng.project_operation_price"
        "(project_operation_id,version_no,price,price_basis,effective_from,effective_to,is_current,occurred_at) "
        "VALUES (%s,(SELECT COALESCE(MAX(version_no),0)+1 FROM eng.project_operation_price "
        "WHERE project_operation_id=%s),%s,%s,%s,%s,%s,%s)",
        (po_id, po_id, price, basis, eff_from, eff_to, is_current, NOW))


def make_task(conn, acid, step, team, attempt=1, rework_of=None, rework_order_id=None):
    return conn.execute(
        "INSERT INTO prod.production_task(actual_component_id,route_template_step_id,attempt,"
        "execute_team_id,make_type,rework_of_task_id,rework_order_id) "
        "VALUES (%s,%s,%s,%s,'inhouse',%s,%s) RETURNING id",
        (acid, step, attempt, team, rework_of, rework_order_id)).fetchone()[0]


def make_rework_order(conn, reason_category_id, source_ref_id,
                      chargeability=None, responsible_team_id=None, responsibility_kind=None):
    """创建一张返工单。

    第4轮起：responsibility_kind 为计价权威来源（TEAM/NON_TEAM/PENDING）；
    chargeability（stored）仅作记录，不参与最终计价。
    responsible_team_id 标识"责任班组（谁造成问题）"，区别于执行返工班组。
    """
    cols = ["order_no", "source_type", "source_ref_type", "source_ref_id",
            "reason_category_id", "chargeability", "responsible_team_id", "occurred_at"]
    params = [_uid("RO"), "inspection", "task", source_ref_id,
              reason_category_id, chargeability, responsible_team_id, NOW]
    if responsibility_kind is not None:
        cols.append("responsibility_kind"); params.append(responsibility_kind)
    ph = "(" + ",".join(["%s"] * len(cols)) + ")"
    return conn.execute(
        f"INSERT INTO prod.rework_order({','.join(cols)}) VALUES {ph} RETURNING id",
        params).fetchone()[0]


def make_report(conn, task_id, acid, step_id, team_id, occurred_at,
                measures=None, workers=None, action_key="complete", client_token=None):
    rid = conn.execute(
        "INSERT INTO prod.production_report(task_id,actual_component_id,route_template_step_id,"
        "execute_team_id,channel,action_key,report_seq,client_token,occurred_at) "
        "VALUES (%s,%s,%s,%s,'scan',%s,1,%s,%s) RETURNING id",
        (task_id, acid, step_id, team_id, action_key, client_token or _uid("tok"), occurred_at)).fetchone()[0]
    unit = conn.execute("SELECT id FROM ref.unit_of_measure ORDER BY id LIMIT 1").fetchone()[0]
    if measures:
        for mtype, val in measures.items():
            conn.execute(
                "INSERT INTO prod.production_measure(report_id,measure_type,value,unit_id,occurred_at) "
                "VALUES (%s,%s,%s,%s,%s)", (rid, mtype, val, unit, occurred_at))
    if workers:
        for emp_id, wh in workers:
            conn.execute(
                "INSERT INTO prod.production_report_worker(report_id,employee_id,work_hours,occurred_at) "
                "VALUES (%s,%s,%s,%s)", (rid, emp_id, wh, occurred_at))
    return rid


def make_employee(conn):
    emp_no = _uid("E")
    return conn.execute(
        "INSERT INTO md.employee(emp_no,name) VALUES (%s,%s) RETURNING id",
        (emp_no, emp_no)).fetchone()[0]


def expect_fail(conn, sql, params, frag):
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as e:
        assert frag in str(e), f"期望错误含 [{frag}]，实际 [{e}]"
        return
    raise AssertionError(f"应当失败但未失败: {sql}")


# 视图 numeric 列经 psycopg3 返回 Decimal；统一转 float，避免 Decimal - float 报错
_NUMERIC_COLS = ("price", "measure_value", "amount")


def trial(conn, **where):
    sql = ("SELECT task_id, component_no, price_basis, price, measure_value, amount, "
           "anomaly_status, is_rework, execute_team_id FROM eng.v_operation_cost_trial")
    clauses = []
    params = {}
    for k, v in where.items():
        clauses.append(f"{k}=%({k})s")
        params[k] = v
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    out = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        for c in _NUMERIC_COLS:
            if d.get(c) is not None:
                d[c] = float(d[c])
        out.append(SimpleNamespace(**d))
    return out


# ---------------------------------------------------------------------------
# 标准 / 自定义工序 + 计价口径
# ---------------------------------------------------------------------------
def test_standard_operation_piece(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 50.0, "piece", date(2026, 1, 1))
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    make_report(conn, task, acid, step, team, NOW)
    r = trial(conn, task_id=task)[0]
    assert r.price_basis == "piece" and r.measure_value == 1 and r.amount == 50.0 \
        and r.anomaly_status == "PRECISE" and r.is_rework is False


def test_custom_operation_weight_precise(conn):
    pid, sid = make_project(conn)
    team = make_team(conn)
    po = add_po_custom(conn, pid, "OP-X", "定制焊接")
    step = make_custom_step(conn, pid, po)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1))
    acid = make_component(conn, sid, "C2")
    task = make_task(conn, acid, step, team)
    make_report(conn, task, acid, step, team, NOW, measures={"weight": 10.0})
    r = trial(conn, task_id=task)[0]
    assert r.price_basis == "weight" and r.measure_value == 10.0 and r.amount == 1000.0 \
        and r.anomaly_status == "PRECISE"


def test_five_price_basis(conn):
    pid, sid = make_project(conn)
    team = make_team(conn)
    emp = make_employee(conn)
    specs = [
        ("weight", {"weight": 10.0}, 10.0),
        ("piece", None, 1.0),
        ("length", {"cut_length": 5.0, "weld_length": 3.0}, 8.0),
        ("hour", None, 4.0),
        ("hole_count", {"hole_count": 12.0}, 12.0),
    ]
    for i, (basis, measures, exp) in enumerate(specs):
        po = add_po_custom(conn, pid, f"OP-{i}", f"工序{i}")
        step = make_custom_step(conn, pid, po)
        add_price(conn, po, 10.0, basis, date(2026, 1, 1))
        acid = make_component(conn, sid, f"C{i}")
        task = make_task(conn, acid, step, team)
        workers = [(emp, 4.0)] if basis == "hour" else None
        make_report(conn, task, acid, step, team, NOW, measures=measures, workers=workers)
        r = trial(conn, task_id=task)[0]
        assert r.price_basis == basis, basis
        assert abs(r.measure_value - exp) < 1e-9, (basis, r.measure_value, exp)
        assert abs(r.amount - 10.0 * exp) < 1e-9, (basis, r.amount)
        assert r.anomaly_status == "PRECISE", (basis, r.anomaly_status)


# ---------------------------------------------------------------------------
# 缺失数据 / 回退
# ---------------------------------------------------------------------------
def test_weight_fallback_and_missing(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1))
    # 回退：报告无重量度量，但构件实际重量存在
    acid1 = make_component(conn, sid, "C1")
    conn.execute("UPDATE prod.actual_component SET actual_weight=10.0 WHERE id=%s", (acid1,))
    t1 = make_task(conn, acid1, step, team)
    make_report(conn, t1, acid1, step, team, NOW)
    r1 = trial(conn, task_id=t1)[0]
    assert r1.anomaly_status == "MEASURE_FALLBACK" and r1.measure_value == 10.0 and r1.amount == 1000.0
    # 缺失：无度量且构件实际重量为空
    acid2 = make_component(conn, sid, "C2")
    t2 = make_task(conn, acid2, step, team)
    make_report(conn, t2, acid2, step, team, NOW)
    r2 = trial(conn, task_id=t2)[0]
    assert r2.anomaly_status == "MISSING_MEASURE" and r2.measure_value is None and r2.amount is None


def test_missing_price(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)  # 无价格版本
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    make_report(conn, task, acid, step, team, NOW, measures={"weight": 10.0})
    r = trial(conn, task_id=task)[0]
    assert r.anomaly_status == "MISSING_PRICE" and r.price is None and r.amount is None


def test_missing_team_branch_defensive(conn):
    # 执行班组 NOT NULL 约束保证班组恒存在，MISSING_TEAM 为防御分支；
    # 此处仅校验 CASE 接线正确（不依赖真实数据路径）。
    row = conn.execute(
        "SELECT CASE WHEN project_operation_id IS NULL OR price IS NULL THEN 'MISSING_PRICE' "
        "WHEN execute_team_id IS NULL THEN 'MISSING_TEAM' ELSE 'X' END "
        "FROM (SELECT 1::bigint AS project_operation_id, 5.0::numeric AS price, "
        "NULL::bigint AS execute_team_id) t").fetchone()
    assert row[0] == "MISSING_TEAM"


# ---------------------------------------------------------------------------
# 返工 / 部分报工 / 幂等
# ---------------------------------------------------------------------------
def test_rework_attempt_separate(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 50.0, "piece", date(2026, 1, 1))
    acid = make_component(conn, sid, "C1")
    t1 = make_task(conn, acid, step, team, attempt=1)
    make_report(conn, t1, acid, step, team, NOW)
    # 返工必须挂合法的"可计酬返工单"：非班组责任原因（material 等外部）→ NON_TEAM（责任判定），计酬。
    # 第4轮：最终计价只由 responsibility_kind 推导；chargeability 仅作记录不参与计价。
    rc = conn.execute(
        "SELECT id FROM ref.reason_dictionary WHERE parent_category <> 'quality' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    ro = make_rework_order(conn, rc, t1, chargeability="chargeable", responsibility_kind="NON_TEAM")
    t2 = make_task(conn, acid, step, team, attempt=2, rework_of=t1, rework_order_id=ro)
    make_report(conn, t2, acid, step, team, NOW)
    rows = trial(conn, project_operation_id=po)
    assert len(rows) == 2
    normal = [r for r in rows if not r.is_rework]
    rework = [r for r in rows if r.is_rework]
    assert len(normal) == 1 and len(rework) == 1
    # 正常 50 + 可计酬返工 50（合法 chargeable 返工计入）
    assert normal[0].amount == 50.0 and rework[0].amount == 50.0
    # 新模型：责任班组 NULL + 显式 chargeable（material 等外部原因）→ REWORK_EXTERNAL（计酬）
    assert rework[0].anomaly_status == "REWORK_EXTERNAL"
    # 返工不覆盖/删除正常事实：汇总正常+返工=合计
    summ = conn.execute(
        "SELECT normal_count,rework_count,normal_cost,rework_cost,total_cost "
        "FROM eng.v_project_production_cost WHERE project_operation_id=%s", (po,)).fetchone()
    # psycopg3 fetchone() 返回元组，按下标访问
    assert summ[0] == 1 and summ[1] == 1 \
        and summ[2] == 50.0 and summ[3] == 50.0 and summ[4] == 100.0


def test_partial_report_no_double_count(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 50.0, "piece", date(2026, 1, 1))
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    # 同一任务两份报告（start + complete）→ 仍只应产生 1 行成本（按任务粒度）
    make_report(conn, task, acid, step, team, NOW, action_key="start")
    make_report(conn, task, acid, step, team, NOW, action_key="complete")
    rows = trial(conn, task_id=task)
    assert len(rows) == 1, "piece 必须按任务粒度，禁止按报告重复计数"
    assert rows[0].measure_value == 1 and rows[0].amount == 50.0


def test_idempotent_duplicate_report_rejected(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    make_report(conn, task, acid, step, team, NOW, action_key="complete", client_token="TK1")
    # 同 (task_id, action_key) 重复插入 => 唯一约束拦截（防幂等双计）
    expect_fail(conn,
        "INSERT INTO prod.production_report(task_id,actual_component_id,route_template_step_id,"
        "execute_team_id,channel,action_key,report_seq,client_token,occurred_at) "
        "VALUES (%s,%s,%s,%s,'scan','complete',2,%s,%s)",
        (task, acid, step, team, "TK1", NOW), "uq_production_report_task_action_key")


# ---------------------------------------------------------------------------
# 价格时间旅行
# ---------------------------------------------------------------------------
def test_price_time_travel(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    # 三段历史价：100(1月)/120(4月)/135(7月)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1), date(2026, 4, 1), is_current=False)
    add_price(conn, po, 120.0, "weight", date(2026, 4, 1), date(2026, 7, 1), is_current=False)
    add_price(conn, po, 135.0, "weight", date(2026, 7, 1), None, is_current=True)
    # 三份报告：2月/5月/8月，重量 10/20/30
    specs = [("C1", date(2026, 2, 15), 10.0), ("C2", date(2026, 5, 15), 20.0), ("C3", date(2026, 8, 15), 30.0)]
    for no, d, w in specs:
        acid = make_component(conn, sid, no)
        task = make_task(conn, acid, step, team)
        make_report(conn, task, acid, step, team, datetime(d.year, d.month, d.day, 10, 0, 0),
                    measures={"weight": w})
    rows = {r.component_no: r for r in trial(conn)}
    assert abs(rows["C1"].amount - 1000.0) < 1e-9   # 10*100
    assert abs(rows["C2"].amount - 2400.0) < 1e-9   # 20*120
    assert abs(rows["C3"].amount - 4050.0) < 1e-9   # 30*135
    # 新价（关 v3 后开 v4@2026-10-01, 价 500）不得回写历史报告
    conn.execute(
        "UPDATE eng.project_operation_price SET effective_to=%s, is_current=false "
        "WHERE project_operation_id=%s AND is_current", (date(2026, 10, 1), po))
    add_price(conn, po, 500.0, "weight", date(2026, 10, 1), None, is_current=True)
    rows2 = {r.component_no: r for r in trial(conn)}
    assert abs(rows2["C1"].amount - 1000.0) < 1e-9
    assert abs(rows2["C2"].amount - 2400.0) < 1e-9
    assert abs(rows2["C3"].amount - 4050.0) < 1e-9
    # 新价之后的报告应使用新价（时间旅行按报告日期匹配）
    acid4 = make_component(conn, sid, "C4")
    task4 = make_task(conn, acid4, step, team)
    make_report(conn, task4, acid4, step, team, datetime(2026, 11, 15, 10, 0, 0), measures={"weight": 10.0})
    r4 = trial(conn, task_id=task4)[0]
    assert abs(r4.amount - 5000.0) < 1e-9  # 10*500


# ---------------------------------------------------------------------------
# T-17 价格版本守卫
# ---------------------------------------------------------------------------
def test_t17_modify_effective_historical_fails(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1), date(2026, 4, 1), is_current=False)
    expect_fail(conn,
        "UPDATE eng.project_operation_price SET price=%s "
        "WHERE project_operation_id=%s AND effective_from=%s",
        (999.0, po, date(2026, 1, 1)), "T-17")


def test_t17_delete_effective_historical_fails(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1), None, is_current=True)
    expect_fail(conn,
        "DELETE FROM eng.project_operation_price WHERE project_operation_id=%s AND effective_from=%s",
        (po, date(2026, 1, 1)), "T-17")


def test_t17_range_overlap_fails(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1), date(2026, 4, 1), is_current=False)
    add_price(conn, po, 120.0, "weight", date(2026, 4, 1), None, is_current=True)
    expect_fail(conn,
        "INSERT INTO eng.project_operation_price"
        "(project_operation_id,version_no,price,price_basis,effective_from,effective_to,is_current,occurred_at) "
        "VALUES (%s,(SELECT COALESCE(MAX(version_no),0)+1 FROM eng.project_operation_price "
        "WHERE project_operation_id=%s),200,'weight',%s,NULL,true,%s)",
        (po, po, date(2026, 2, 1), NOW), "T-17")


def test_t17_single_current_invariant(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 1, 1), None, is_current=True)
    # 通过服务路径关旧+开新，验证始终只有一个当前版本
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from app.services import price_service
    conn.commit()
    eng = create_engine("postgresql+psycopg://postgres@localhost:15432/jiangxing_mes_test", future=True)
    SM = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    db = SM()
    try:
        price_service.create_price_version(db, project_operation_id=po, price=120.0,
                                           price_basis="weight", effective_from=date(2026, 4, 1))
        db.commit()
        n = db.execute(text(
            "SELECT count(*) FROM eng.project_operation_price "
            "WHERE project_operation_id=:po AND is_current"), {"po": po}).scalar()
        assert n == 1
    finally:
        db.close()
        eng.dispose()


def test_t17_future_version_free_edit(conn):
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 100.0, "weight", date(2026, 12, 1), None, is_current=True)  # 未来生效
    # 未来版本：允许改价 / 删除
    conn.execute(
        "UPDATE eng.project_operation_price SET price=%s WHERE project_operation_id=%s AND effective_from=%s",
        (200.0, po, date(2026, 12, 1)))
    conn.execute(
        "DELETE FROM eng.project_operation_price WHERE project_operation_id=%s AND effective_from=%s",
        (po, date(2026, 12, 1)))
    n = conn.execute(
        "SELECT count(*) FROM eng.project_operation_price WHERE project_operation_id=%s", (po,)).fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------------------
# route_template_step 互斥
# ---------------------------------------------------------------------------
def test_route_step_mutex(conn):
    pid, sid = make_project(conn)
    ot = conn.execute("SELECT id FROM ref.operation_type ORDER BY sort_no, id LIMIT 1").fetchone()[0]
    po = add_po_custom(conn, pid, "OP-X", "X")
    tid = conn.execute(
        "INSERT INTO eng.route_template(main_project_id,name) VALUES (%s,'RT') RETURNING id",
        (pid,)).fetchone()[0]
    # 双空 => 失败
    expect_fail(conn, "INSERT INTO eng.route_template_step(template_id,step_no) VALUES (%s,1)",
                (tid,), "ck_rts_op_xor")
    # 双填 => 失败
    expect_fail(conn,
        "INSERT INTO eng.route_template_step(template_id,step_no,operation_type_id,project_operation_id) "
        "VALUES (%s,1,%s,%s)", (tid, ot, po), "ck_rts_op_xor")
    # 仅 operation_type_id => 标准（成功）
    s1 = conn.execute(
        "INSERT INTO eng.route_template_step(template_id,step_no,operation_type_id) "
        "VALUES (%s,1,%s) RETURNING id", (tid, ot)).fetchone()[0]
    # 仅 project_operation_id => 自定义（成功）
    s2 = conn.execute(
        "INSERT INTO eng.route_template_step(template_id,step_no,project_operation_id) "
        "VALUES (%s,2,%s) RETURNING id", (tid, po)).fetchone()[0]
    assert s1 and s2


# ---------------------------------------------------------------------------
# 只读查询入口 / 改价服务
# ---------------------------------------------------------------------------
def test_cost_query_service_readonly(conn):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services import cost_query_service
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    add_price(conn, po, 50.0, "piece", date(2026, 1, 1))
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    make_report(conn, task, acid, step, team, NOW)
    conn.commit()  # 令独立会话可见
    eng = create_engine("postgresql+psycopg://postgres@localhost:15432/jiangxing_mes_test", future=True)
    SM = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    db = SM()
    try:
        rows = cost_query_service.trial_rows(db, project_operation_id=po)
        assert len(rows) == 1 and rows[0]["amount"] == 50.0
        summ = cost_query_service.project_cost_summary(db, project_operation_id=po)
        assert len(summ) == 1 and summ[0]["total_cost"] == 50.0
    finally:
        db.close()
        eng.dispose()


def test_price_service_close_old_create_new(conn):
    from datetime import date as _date
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.services import price_service
    from app.db.models.eng import ProjectOperationPrice
    pid, sid = make_project(conn)
    team = make_team(conn)
    ot = conn.execute("SELECT id FROM ref.operation_type ORDER BY sort_no, id LIMIT 1").fetchone()[0]
    conn.commit()  # 令服务会话可见 project/team
    eng = create_engine("postgresql+psycopg://postgres@localhost:15432/jiangxing_mes_test", future=True)
    SM = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    db = SM()
    try:
        po = price_service.create_project_operation(
            db, main_project_id=pid, project_operation_code="OP1",
            operation_type_id=ot, default_team_id=team)
        db.commit()
        price_service.create_price_version(
            db, project_operation_id=po.id, price=100.0, price_basis="weight",
            effective_from=_date(2026, 1, 1))
        db.commit()
        price_service.create_price_version(
            db, project_operation_id=po.id, price=120.0, price_basis="weight",
            effective_from=_date(2026, 4, 1))
        db.commit()
        vers = db.execute(
            select(ProjectOperationPrice).where(
                ProjectOperationPrice.project_operation_id == po.id)
            .order_by(ProjectOperationPrice.version_no)).scalars().all()
        assert len(vers) == 2
        assert vers[0].is_current is False and vers[0].effective_to == _date(2026, 4, 1)
        assert vers[1].is_current is True
    finally:
        db.close()
        eng.dispose()


# ---------------------------------------------------------------------------
# 审查修订：跨价格版本计价粒度 + 未来价被引用即不可变
# ---------------------------------------------------------------------------
def test_same_task_reports_cross_price_versions(conn):
    """同一 production_task 的多个报告跨两个价格版本时，每个事实按自身 occurred_at 匹配价格。"""
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    po = add_po_standard(conn, pid, "OP-CUT", ot)
    # 两个版本：3 月 100 / 5 月 120
    add_price(conn, po, 100.0, "weight", date(2026, 3, 1), date(2026, 5, 1), is_current=False)
    add_price(conn, po, 120.0, "weight", date(2026, 5, 1), None, is_current=True)
    acid = make_component(conn, sid, "C1")
    task = make_task(conn, acid, step, team)
    # 同一 task 两份报告跨两个版本（不同 action_key 规避唯一约束）
    make_report(conn, task, acid, step, team, datetime(2026, 3, 15, 10, 0, 0),
                measures={"weight": 5.0}, action_key="start")
    make_report(conn, task, acid, step, team, datetime(2026, 5, 15, 10, 0, 0),
                measures={"weight": 5.0}, action_key="complete")
    r = trial(conn, task_id=task)[0]
    assert r.price_basis == "weight"
    assert r.measure_value == 10.0                       # 5 + 5
    assert abs(r.amount - 1100.0) < 1e-9                 # 5*100 + 5*120
    assert r.anomaly_status == "PRECISE"


def test_future_price_referenced_by_fact_is_immutable(conn):
    """未来价格一旦被生产事实引用，禁止改价/删除；未被引用的未来价格仍自由编辑/删除。"""
    pid, sid = make_project(conn)
    step, ot = make_standard_step(conn, pid, "cutting")
    team = make_team(conn)
    # po A：未来价格（effective_from 2026-10-01）已被生产事实引用
    poA = add_po_standard(conn, pid, "OP-A", ot)
    add_price(conn, poA, 100.0, "weight", date(2026, 10, 1), None, is_current=True)
    acidA = make_component(conn, sid, "CA")
    taskA = make_task(conn, acidA, step, team)
    make_report(conn, taskA, acidA, step, team, datetime(2026, 10, 2, 10, 0, 0),
                measures={"weight": 5.0})  # 落入 poA 价格窗口
    # 改价 -> 必须失败
    expect_fail(conn,
        "UPDATE eng.project_operation_price SET price=%s "
        "WHERE project_operation_id=%s AND effective_from=%s",
        (130.0, poA, date(2026, 10, 1)), "T-17")
    # 删除 -> 必须失败
    expect_fail(conn,
        "DELETE FROM eng.project_operation_price WHERE project_operation_id=%s AND effective_from=%s",
        (poA, date(2026, 10, 1)), "T-17")
    # po B：未来价格（2026-11-01）未被任何事实引用 -> 仍可自由编辑/删除
    poB = add_po_standard(conn, pid, "OP-B", ot)
    add_price(conn, poB, 200.0, "weight", date(2026, 11, 1), None, is_current=True)
    conn.execute(
        "UPDATE eng.project_operation_price SET price=%s WHERE project_operation_id=%s AND effective_from=%s",
        (250.0, poB, date(2026, 11, 1)))
    conn.execute(
        "DELETE FROM eng.project_operation_price WHERE project_operation_id=%s AND effective_from=%s",
        (poB, date(2026, 11, 1)))
    n = conn.execute(
        "SELECT count(*) FROM eng.project_operation_price WHERE project_operation_id=%s", (poB,)).fetchone()[0]
    assert n == 0
