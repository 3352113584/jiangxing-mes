"""劳务验收整改（第 4 轮）：responsibility_kind 责任判定 + 防旁路 真实数据库链路验收。

对照用户整改指令 §二~§十一：
- §二/§五/§六：把"返工为什么发生、谁负责、谁执行、是否计价"彻底分开；
  不再通过 responsible_team_id != execute_team_id 猜测责任；最终计价只由 responsibility_kind 推导。
- §三/§四：明确责任判定结果 responsibility_kind（TEAM / NON_TEAM / PENDING），
  rework_order.chargeability（stored）只是记录/缓存，不可绕过责任判定成为第二套规则。
- §七：DB 层防旁路（TEAM 必须责任班组、NON_TEAM 责任班组必须为 NULL、PENDING 禁止 chargeable）。
- §九：v_operation_cost_trial / v_project_production_cost / labor_settlement_service 三入口同一规则。
- §十：8 个真实场景（含"人工写 chargeable 不被静默覆盖"与"quality≠班组责任"）三入口一致。
- §十一：ORM / DB / migration 三者一致（chargeability 三值 CK 已同步）。

所有断言基于真实 PostgreSQL（jiangxing_mes_test @ :15432）执行结果，不修改任何金额期望值掩盖业务问题。
"""
import psycopg
import pytest

from conftest import fails
from helpers import B
from datetime import date, datetime

from app.services.labor_settlement_service import (
    classify_chargeability,
    compute_task_labor_cost,
    resolve_labor_unit_price,
)

EFFECTIVE = date(2026, 9, 18)
NOW_DT = datetime(2026, 9, 18, 10, 0, 0)  # BFactMixin.occurred_at 非空


# ============ 测试内小工具 ============
def _ref(conn, table, cols="id"):
    return conn.execute(f"SELECT {cols} FROM ref.{table} ORDER BY id LIMIT 1").fetchone()


def _reason(conn, parent_category):
    return conn.execute(
        "SELECT id FROM ref.reason_dictionary WHERE parent_category=%s ORDER BY id LIMIT 1",
        (parent_category,)).fetchone()[0]


def _make_rework(conn, reason_cat_id, chargeability=None, responsible_team_id=None,
                 responsibility_kind=None):
    order_no = f"RO{conn.execute('SELECT count(*)+1 FROM prod.rework_order').fetchone()[0]}"
    cols = ["order_no", "source_type", "source_ref_type", "source_ref_id",
            "reason_category_id", "occurred_at"]
    params = [order_no, "inspection", "task", 0, reason_cat_id, NOW_DT]
    if chargeability is not None:
        cols.append("chargeability"); params.append(chargeability)
    if responsible_team_id is not None:
        cols.append("responsible_team_id"); params.append(responsible_team_id)
    if responsibility_kind is not None:
        cols.append("responsibility_kind"); params.append(responsibility_kind)
    ph = "(" + ",".join(["%s"] * len(cols)) + ")"
    sql = f"INSERT INTO prod.rework_order({','.join(cols)}) VALUES {ph} RETURNING id"
    return conn.execute(sql, params).fetchone()[0]


def _make_task(conn, ac, step, team, rework_of=None, rework_order_id=None, attempt=1):
    return conn.execute(
        "INSERT INTO prod.production_task(actual_component_id, route_template_step_id, attempt, "
        "execute_team_id, make_type, rework_of_task_id, rework_order_id) "
        "VALUES (%s,%s,%s,%s,'inhouse',%s,%s) RETURNING id",
        (ac, step, attempt, team, rework_of, rework_order_id),
    ).fetchone()[0]


def _setup_base_rule(conn, ctid, opid, unit_id, price=100.0):
    """插入基础价规则（构件类型×标准工序，通用班组）当前版本。返回 rule_id。"""
    rule_id = conn.execute(
        "INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, "
        "price_unit_id, is_active) VALUES (%s,%s,%s,%s,true) RETURNING id",
        (f"R{conn.execute('SELECT count(*)+1 FROM eng.labor_pricing_rule').fetchone()[0]}",
         ctid, opid, unit_id),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
        "VALUES (%s,1,%s,%s,true,%s)",
        (rule_id, price, EFFECTIVE, NOW_DT),
    )
    return rule_id


def _setup_po_price(conn, pid, opid, price=100.0):
    """为视图项目价建 project_operation + project_operation_price（piece，100 元）。"""
    po_id = conn.execute(
        "INSERT INTO eng.project_operation(main_project_id, project_operation_code, operation_type_id, is_active) "
        "VALUES (%s,'PO_ACCEPT',%s,true) RETURNING id", (pid, opid)).fetchone()[0]
    conn.execute(
        "INSERT INTO eng.project_operation_price(project_operation_id, version_no, price, price_basis, effective_from, is_current, occurred_at) "
        "VALUES (%s,1,%s,'piece',%s,true,%s)", (po_id, price, EFFECTIVE, NOW_DT))
    return po_id


def _build_component(conn, b, sid, ctid, opid):
    """构造 构件 + 标准路线步骤（步骤工序=opid），返回 (ac_id, step_id)。"""
    cli = b.list_item(sid)
    ac = b.component(sid, cli, "C1")
    conn.execute("UPDATE prod.actual_component SET component_type_id=%s WHERE id=%s", (ctid, ac))
    rt = conn.execute("INSERT INTO eng.route_template(subproject_id, name) VALUES (%s,'路线') RETURNING id",
                      (sid,)).fetchone()[0]
    step = conn.execute(
        "INSERT INTO eng.route_template_step(template_id, step_no, operation_type_id) VALUES (%s,1,%s) RETURNING id",
        (rt, opid)).fetchone()[0]
    return ac, step


# ============ §五/§九：服务层 classify 以 responsibility_kind 为权威来源 ============
class TestClassifyByResponsibilityKind:
    def test_classify_without_basis_is_non_chargeable(self):
        # 无责任依据 / PENDING / 未知 → 不可结算（不默认放行）
        assert classify_chargeability(None, True) == "non_chargeable"
        assert classify_chargeability("PENDING", True) == "non_chargeable"
        assert classify_chargeability("garbage", True) == "non_chargeable"
        # 正常作业（非返工）不受影响
        assert classify_chargeability(None, False) == "chargeable"
        assert classify_chargeability("TEAM", False) == "chargeable"

    def test_classify_by_responsibility_relationship(self):
        # TEAM + 责任==执行（自责返工）→ non_chargeable
        assert classify_chargeability("TEAM", True, responsible_team_id=1, execute_team_id=1) == "non_chargeable"
        # TEAM + 责任!=执行（他人/前道工序责任）→ chargeable（执行方计酬）
        assert classify_chargeability("TEAM", True, responsible_team_id=1, execute_team_id=2) == "chargeable"
        # NON_TEAM（外部责任）→ chargeable（执行方计酬）
        assert classify_chargeability("NON_TEAM", True) == "chargeable"
        # PENDING/NULL → 不可结算
        assert classify_chargeability("PENDING", True) == "non_chargeable"
        assert classify_chargeability(None, True) == "non_chargeable"

    def test_attempt_gt1_without_rework_order_amount_zero(self, conn):
        """无 responsibility_kind 且 attempt>1 的返工，无明确可计酬依据 → amount 0（服务层）。"""
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        ac, step = _build_component(conn, b, sid, ct, op)
        team = b.team()
        _setup_base_rule(conn, ct, op, unit, price=100.0)
        res = compute_task_labor_cost(
            conn, component_type_id=ct, operation_type_id=op, team_id=team,
            effective_date=EFFECTIVE, quantity=1.0, is_rework=True)  # 无 responsibility_kind → 不可结算
        assert res["chargeable"] is False and res["amount"] == 0.0


# ============ §七/§十一：DB 层防旁路（CK 守卫） ============
class TestResponsibilityGuards:
    def test_chargeability_null_defaults_to_pending(self, conn):
        """chargeability=NULL 不再绕过守卫 → 默认 'pending'（待确认/不可结算）。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        ro = conn.execute(
            "INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
            "reason_category_id, occurred_at) VALUES ('RD1','inspection','task',0,%s,now()) RETURNING id, chargeability",
            (rc,)).fetchone()
        assert ro[1] == 'pending', "chargeability=NULL 应默认 pending，而非放行计价"

    def test_illegal_chargeability_blocked_by_check(self, conn):
        """'bogus' 等非法值仍由 ck_rework_order_chargeability_values 拦截。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
              f"reason_category_id, chargeability, occurred_at) "
              f"VALUES ('BAD','inspection','task',0,{rc},'bogus',now())",
              frag="ck_rework_order_chargeability_values")

    def test_reason_no_longer_drives_chargeability(self, conn):
        """RED-A：reason 的 parent_category（异常分类）不再推导 chargeability。
        质量原因 + 合法责任判定(NON_TEAM) + 显式 'chargeable' 应允许写入（不被 parent_category 拦截）。
        （ORANGE-3：NULL+chargeable 已被 DB 拒绝，故须带合法 responsibility_kind 才允许 chargeable。）"""
        b = B(conn)
        rc_quality = _reason(conn, 'quality')
        ro = conn.execute(
            "INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
            "reason_category_id, responsibility_kind, chargeability, occurred_at) "
            "VALUES ('RQ1','inspection','task',0,%s,'NON_TEAM','chargeable',now()) RETURNING id, chargeability",
            (rc_quality,)).fetchone()
        assert ro[1] == 'chargeable'

    def test_team_requires_responsible_team_id(self, conn):
        """§七-1：TEAM + responsible_team_id=NULL → 禁止。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
              f"reason_category_id, responsibility_kind, occurred_at) "
              f"VALUES ('T1','inspection','task',0,{rc},'TEAM',now())",
              frag="ck_rework_order_resp_team")

    def test_non_team_requires_null_responsible_team_id(self, conn):
        """§七-2：NON_TEAM + responsible_team_id 非空 → 禁止（不得被误当责任班组）。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        team = b.team()
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
              f"reason_category_id, responsibility_kind, responsible_team_id, occurred_at) "
              f"VALUES ('T2','inspection','task',0,{rc},'NON_TEAM',{team},now())",
              frag="ck_rework_order_resp_team")

    def test_pending_cannot_be_chargeable(self, conn):
        """§七-3：PENDING + chargeability='chargeable' → 禁止进入计价。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
              f"reason_category_id, responsibility_kind, chargeability, occurred_at) "
              f"VALUES ('T3','inspection','task',0,{rc},'PENDING','chargeable',now())",
              frag="ck_rework_order_pending_chargeable")

    def test_null_kind_cannot_be_chargeable(self, conn):
        """ORANGE-3（R6）：responsibility_kind=NULL ≡ PENDING，不得记为可计价。
        NULL + chargeability='chargeable' 必须被 DB 拒绝（ck_rework_order_null_chargeable）。"""
        b = B(conn)
        rc = _ref(conn, "reason_dictionary")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, "
              f"reason_category_id, chargeability, occurred_at) "
              f"VALUES ('T3b','inspection','task',0,{rc},'chargeable',now())",
              frag="ck_rework_order_null_chargeable")

    def test_responsible_team_id_traceable(self, conn):
        """责任班组可记录，与执行返工班组区分（NON_TEAM 时责任班组为 NULL）。"""
        b = B(conn)
        rc = _reason(conn, 'material')
        teamA = b.team(); teamB = b.team()
        ro = _make_rework(conn, rc, chargeability='pending', responsible_team_id=teamA,
                          responsibility_kind='TEAM')
        row = conn.execute(
            "SELECT responsibility_kind, chargeability, responsible_team_id FROM prod.rework_order WHERE id=%s",
            (ro,)).fetchone()
        assert row[0] == 'TEAM' and row[1] == 'pending' and row[2] == teamA
        # 执行班组在 production_task.execute_team_id，可与 responsible_team_id 不同
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        ac, step = _build_component(conn, b, sid, ct, op)
        t = _make_task(conn, ac, step, teamB, rework_order_id=ro, attempt=2)
        trow = conn.execute(
            "SELECT execute_team_id, rework_order_id FROM prod.production_task WHERE id=%s", (t,)).fetchone()
        assert trow[0] == teamB and trow[1] == ro  # 执行方 teamB ≠ 责任方 teamA


# ============ §三：labor_pricing_rule_version 历史不可变 ============
class TestPriceVersionImmutable:
    def test_immutable_and_time_travel(self, conn):
        b = B(conn)
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        rule_id = conn.execute(
            "INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, price_unit_id, is_active) "
            "VALUES ('IMMUT',%s,%s,%s,true) RETURNING id", (ct, op, unit)).fetchone()[0]
        OLD = date(2026, 9, 1)
        old_id = conn.execute(
            "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
            "VALUES (%s,1,100,%s,true,%s) RETURNING id", (rule_id, OLD, NOW_DT)).fetchone()[0]
        assert resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                        effective_date=date(2026, 9, 10)) == 100.0
        NEW = date(2026, 9, 15)
        conn.execute("UPDATE eng.labor_pricing_rule_version SET is_current=false WHERE id=%s", (old_id,))
        conn.execute(
            "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
            "VALUES (%s,2,120,%s,true,%s)", (rule_id, NEW, NOW_DT))
        assert resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                        effective_date=date(2026, 9, 10)) == 100.0
        assert resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                        effective_date=date(2026, 9, 16)) == 120.0
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE eng.labor_pricing_rule_version SET unit_price=999 WHERE id={old_id}",
              frag="已生效版本禁止修改")
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM eng.labor_pricing_rule_version WHERE id={old_id}",
              frag="禁止删除")
        fut_id = conn.execute(
            "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
            "VALUES (%s,3,200,'2099-01-01',false,%s) RETURNING id", (rule_id, NOW_DT)).fetchone()[0]
        conn.execute("DELETE FROM eng.labor_pricing_rule_version WHERE id=%s", (fut_id,))


# ============ §十：8 个真实返工责任场景，视图/服务/汇总三入口一致 ============
class TestReworkResponsibilityScenarios:
    def _setup_scenario(self, conn, *, reason_parent, responsibility_kind, responsible_team_id,
                        stored_chargeability, rework_execute_team):
        """构造一个返工责任场景，返回上下文字典。

        responsibility_kind: 明确责任判定（TEAM/NON_TEAM/PENDING）；权威计价来源。
        responsible_team_id: 责任班组（TEAM 时必填）；NON_TEAM 时为 NULL。
        stored_chargeability: rework_order.chargeability 的记录值（可为 None→默认 pending）；
            仅作记录，不参与最终计价；验证场景⑤⑥不被静默覆盖。
        rework_execute_team: 执行返工班组（production_task.execute_team_id）。
        """
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        ac, step = _build_component(conn, b, sid, ct, op)
        # 原作业（正常完成）班组：责任方即原作业方（自责时等于返工执行方）
        normal_team = responsible_team_id if responsible_team_id is not None else b.team()
        _setup_base_rule(conn, ct, op, unit, price=100.0)   # 服务层基础价 100
        _setup_po_price(conn, pid, op, price=100.0)          # 视图 project_operation_price 100 (piece)
        rc = _reason(conn, reason_parent)
        t1 = _make_task(conn, ac, step, normal_team)               # 正常作业（前道工序/原作业）
        b.report(t1, ac, step, normal_team, action_key="start", client_token="t1", seq=1)
        ro = _make_rework(conn, rc, chargeability=stored_chargeability,
                          responsible_team_id=responsible_team_id, responsibility_kind=responsibility_kind)
        t2 = _make_task(conn, ac, step, rework_execute_team, rework_of=t1, rework_order_id=ro, attempt=2)
        b.report(t2, ac, step, rework_execute_team, action_key="start", client_token="t2", seq=1)
        return dict(t1=t1, t2=t2, ro=ro, ct=ct, op=op, normal_team=normal_team,
                    rework_execute_team=rework_execute_team,
                    responsible_team_id=responsible_team_id,
                    responsibility_kind=responsibility_kind,
                    stored_chargeability=stored_chargeability)

    def _assert_three_entries(self, conn, ctx, expected_rework_amount, expected_anomaly,
                              expected_stored=None):
        t1, t2, ro = ctx["t1"], ctx["t2"], ctx["ro"]
        ct, op = ctx["ct"], ctx["op"]
        normal_team, rework_execute_team = ctx["normal_team"], ctx["rework_execute_team"]
        responsible_team_id = ctx["responsible_team_id"]
        responsibility_kind = ctx["responsibility_kind"]

        # 1) 视图 v_operation_cost_trial：逐任务金额 + 责任依据可见
        rows = conn.execute(
            "SELECT task_id, is_rework, effective_chargeability, amount, anomaly_status, "
            "responsible_team_id, pricing_basis, stored_chargeability "
            "FROM eng.v_operation_cost_trial WHERE task_id IN (%s,%s) ORDER BY task_id", (t1, t2)).fetchall()
        by = {r[0]: r for r in rows}
        assert by[t1][1] is False and by[t1][3] == 100.0, f"正常任务应为 100，实际 {by[t1][3]}"
        assert by[t2][1] is True and by[t2][3] == expected_rework_amount, \
            f"返工任务应为 {expected_rework_amount}，实际 {by[t2][3]}"
        assert by[t2][4] == expected_anomaly, f"anomaly 应为 {expected_anomaly}，实际 {by[t2][4]}"
        # 责任班组可追溯（自责场景责任=执行；外部场景责任=NULL）
        assert by[t2][5] == responsible_team_id, f"responsible_team_id 应为 {responsible_team_id}"
        # ⑤⑥：stored chargeability 不得被静默覆盖
        if expected_stored is not None:
            assert by[t2][7] == expected_stored, \
                f"stored chargeability 不应被静默覆盖，实际 {by[t2][7]}（应为 {expected_stored}）"

        # 2) 视图 v_project_production_cost：汇总一致
        agg = conn.execute(
            "SELECT SUM(normal_cost), SUM(rework_cost), SUM(total_cost), "
            "SUM(normal_count), SUM(rework_count) FROM eng.v_project_production_cost").fetchone()
        assert agg[3] == 1 and agg[4] == 1
        assert agg[0] == 100.0 and agg[1] == expected_rework_amount and agg[2] == 100.0 + expected_rework_amount

        # 3) 服务层 compute_task_labor_cost：与视图一致（基于 responsibility_kind 推导）
        s1 = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=normal_team,
                                    effective_date=EFFECTIVE, quantity=1.0)["amount"]
        s2 = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=rework_execute_team,
                                    effective_date=EFFECTIVE, quantity=1.0,
                                    responsibility_kind=responsibility_kind,
                                    is_rework=True,
                                    responsible_team_id=responsible_team_id,
                                    execute_team_id=rework_execute_team)["amount"]
        assert s1 == 100.0 and s2 == expected_rework_amount

    # ① TEAM A → A 返工（自责）：A 只计一次
    def test_scenario_1_team_self_blame_self_rework(self, conn):
        b = B(conn)
        teamA = b.team()
        ctx = self._setup_scenario(conn, reason_parent='quality',
                                   responsibility_kind='TEAM', responsible_team_id=teamA,
                                   stored_chargeability='non_chargeable', rework_execute_team=teamA)
        self._assert_three_entries(conn, ctx, expected_rework_amount=0.0,
                                   expected_anomaly='REWORK_SELF_RESPONSIBLE')

    # ② TEAM A → B 返工：B 正常计价，A 不因返工再次计价
    def test_scenario_2_team_A_blame_B_rework(self, conn):
        b = B(conn)
        teamA = b.team(); teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='production_organization',
                                   responsibility_kind='TEAM', responsible_team_id=teamA,
                                   stored_chargeability='chargeable', rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=100.0,
                                   expected_anomaly='REWORK_OTHER_RESPONSIBLE')

    # ③ NON_TEAM → B 返工（前道工序/外部责任）：B 正常计价
    def test_scenario_3_non_team_B_rework(self, conn):
        b = B(conn)
        teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='quality',
                                   responsibility_kind='NON_TEAM', responsible_team_id=None,
                                   stored_chargeability='chargeable', rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=100.0,
                                   expected_anomaly='REWORK_EXTERNAL')

    # ④ PENDING → B 返工：责任未确认，不得进入正式劳务计价
    def test_scenario_4_pending_B_rework(self, conn):
        b = B(conn)
        teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='other',
                                   responsibility_kind='PENDING', responsible_team_id=None,
                                   stored_chargeability=None, rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=0.0,
                                   expected_anomaly='REWORK_NO_BASIS')

    # ⑤ TEAM A → B 返工，但人工写 chargeability='non_chargeable'：禁止静默覆盖，按责任规则计酬
    def test_scenario_5_team_A_blame_B_rework_stored_non_chargeable(self, conn):
        b = B(conn)
        teamA = b.team(); teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='production_organization',
                                   responsibility_kind='TEAM', responsible_team_id=teamA,
                                   stored_chargeability='non_chargeable', rework_execute_team=teamB)
        # 最终按 responsibility_kind 计酬（B 可计），但 stored 不被静默改成 chargeable
        self._assert_three_entries(conn, ctx, expected_rework_amount=100.0,
                                   expected_anomaly='REWORK_OTHER_RESPONSIBLE',
                                   expected_stored='non_chargeable')

    # ⑥ TEAM A → B 返工，但人工写 chargeability='pending'：禁止静默变成 chargeable
    def test_scenario_6_team_A_blame_B_rework_stored_pending(self, conn):
        b = B(conn)
        teamA = b.team(); teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='production_organization',
                                   responsibility_kind='TEAM', responsible_team_id=teamA,
                                   stored_chargeability='pending', rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=100.0,
                                   expected_anomaly='REWORK_OTHER_RESPONSIBLE',
                                   expected_stored='pending')

    # ⑦ 无 responsibility_kind（无责任依据）：不得产生正式计价。
    # ORANGE-3：NULL+chargeable 已被 DB 拒绝；以合法 stored='non_chargeable' 记录，
    # responsibility_kind=NULL ≡ PENDING → eff 仍 non_chargeable，amount=0。
    def test_scenario_7_no_responsibility_kind(self, conn):
        b = B(conn)
        teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='other',
                                   responsibility_kind=None, responsible_team_id=None,
                                   stored_chargeability='non_chargeable', rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=0.0,
                                   expected_anomaly='REWORK_NO_BASIS')

    # ⑧ quality 类原因 + NON_TEAM：必须允许正常计价（证明 quality ≠ 班组责任）
    def test_scenario_8_quality_reason_non_team_chargeable(self, conn):
        b = B(conn)
        teamB = b.team()
        ctx = self._setup_scenario(conn, reason_parent='quality',
                                   responsibility_kind='NON_TEAM', responsible_team_id=None,
                                   stored_chargeability='chargeable', rework_execute_team=teamB)
        self._assert_three_entries(conn, ctx, expected_rework_amount=100.0,
                                   expected_anomaly='REWORK_EXTERNAL')
