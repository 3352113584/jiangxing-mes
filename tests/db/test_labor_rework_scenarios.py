"""V1.2 劳务业务第2轮整改 — 最小口径自动化测试（M2/M3/M4/M5/M6/M7/M8/M9/M10/M11）。

覆盖：
- M2/M3/M4/M6 新增表的约束（唯一/CHECK/XOR/部分唯一）。
- M5 标准模板→项目实例的"采用/复制"且单向。
- M7 计价来源优先级：项目价 > 基础价 > MISSING_PRICE。
- M8/M9 计价资格 chargeability + 单任务成本（non_chargeable → 0；无价 → 绝不 0）。
- M10 三个返工场景最终金额：A 自责返工 A 只计 1 次；B 自责 A 返工 A=1,B=1；设计变更 B 返工 B 正常计。
- M11 历史不可变：价格版本按 occurred_at 时间旅行匹配，新版本不污染历史。

价格数值（100/80/200）仅为测试夹具，非业务定价（业务价格由运营后续配置，迁移/种子不预填）。
"""
import psycopg
import pytest

from conftest import fails
from helpers import B
from datetime import date, datetime

from app.services.labor_settlement_service import (
    adopt_standard_template,
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
    """取指定 parent_category 的 reason_dictionary id（首个）。"""
    return conn.execute(
        "SELECT id FROM ref.reason_dictionary WHERE parent_category=%s ORDER BY id LIMIT 1",
        (parent_category,)).fetchone()[0]


def _make_rework(conn, chargeability, reason_cat_id, responsibility_kind=None, responsible_team_id=None):
    cols = ["order_no", "source_type", "source_ref_type", "source_ref_id",
            "reason_category_id", "chargeability", "occurred_at"]
    placeholders = ["%s", "'inspection'", "'task'", "0", "%s", "%s", "%s"]
    params = [f"RO{conn.execute('SELECT count(*)+1 FROM prod.rework_order').fetchone()[0]}",
              reason_cat_id, chargeability, NOW_DT]
    if responsibility_kind is not None:
        cols.append("responsibility_kind"); placeholders.append("%s"); params.append(responsibility_kind)
    if responsible_team_id is not None:
        cols.append("responsible_team_id"); placeholders.append("%s"); params.append(responsible_team_id)
    sql = f"INSERT INTO prod.rework_order({','.join(cols)}) VALUES ({','.join(placeholders)}) RETURNING id"
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
        (f"R{conn.execute('SELECT count(*)+1 FROM eng.labor_pricing_rule').fetchone()[0]}", ctid, opid, unit_id),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
        "VALUES (%s,1,%s,%s,true,%s)",
        (rule_id, price, EFFECTIVE, NOW_DT),
    )
    return rule_id


def _build_component(conn, b, sid, ctid, opid):
    """构造 构件 + 标准路线步骤（步骤工序=opid），返回 (ac_id, step_id)。"""
    cli = b.list_item(sid)
    ac = b.component(sid, cli, "C1")
    conn.execute("UPDATE prod.actual_component SET component_type_id=%s WHERE id=%s", (ctid, ac))
    # 用指定 opid 建路线步骤（绕过 B.route_step 的默认首个工序）；N-6 双归属由 subproject_id 满足
    rt = conn.execute("INSERT INTO eng.route_template(subproject_id, name) VALUES (%s,'路线') RETURNING id",
                      (sid,)).fetchone()[0]
    step = conn.execute(
        "INSERT INTO eng.route_template_step(template_id, step_no, operation_type_id) VALUES (%s,1,%s) RETURNING id",
        (rt, opid)).fetchone()[0]
    return ac, step


# ============ M2/M3/M4/M6 约束 ============
class TestNewTableConstraints:
    def test_m2_team_operation_capability_unique(self, conn):
        b = B(conn)
        team = b.team(); op = b.op_type()
        conn.execute("INSERT INTO md.team_operation_capability(team_id, operation_type_id) VALUES (%s,%s)", (team, op))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO md.team_operation_capability(team_id, operation_type_id) VALUES (%s,%s)", (team, op))

    def test_m3_employee_occupation_unique(self, conn):
        b = B(conn)
        emp = conn.execute(
            "INSERT INTO md.employee(emp_no, name) VALUES (%s,'测试员工') RETURNING id",
            (f"E{conn.execute('SELECT count(*)+1 FROM md.employee').fetchone()[0]}",)).fetchone()[0]
        occ = _ref(conn, "employee_occupation_dict")[0]
        conn.execute("INSERT INTO md.employee_occupation(employee_id, occupation_id) VALUES (%s,%s)", (emp, occ))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO md.employee_occupation(employee_id, occupation_id) VALUES (%s,%s)", (emp, occ))

    def test_m4_step_xor_both_and_neither_fail(self, conn):
        b = B(conn)
        tpl = conn.execute(
            "INSERT INTO eng.component_type_process_template(component_type_id, version_no, status) "
            "VALUES (%s,1,'active') RETURNING id", (_ref(conn, "component_type_dict")[0],)).fetchone()[0]
        op = b.op_type()
        # 既给 operation_type_id 又给 project_operation_id → 失败
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO eng.component_type_process_step(template_id, step_no, operation_type_id, project_operation_id) "
              f"VALUES ({tpl},1,{op},{op})", frag="ck_ctps_op_xor")
        # 都不给 → 失败
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO eng.component_type_process_step(template_id, step_no) VALUES ({tpl},2)",
              frag="ck_ctps_op_xor")

    def test_m4_status_check(self, conn):
        ct = _ref(conn, "component_type_dict")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO eng.component_type_process_template(component_type_id, version_no, status) "
              f"VALUES ({ct},1,'bogus')", frag="ck_ctpt_status_values")

    def test_m6_rule_dim_unique(self, conn):
        b = B(conn)
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        _setup_base_rule(conn, ct, op, unit, price=100.0)
        # 相同 (构件类型, 工序, 通用班组) 再插 → 唯一冲突
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, price_unit_id, is_active) "
                "VALUES ('DUP',%s,%s,%s,true)", (ct, op, unit))

    def test_m6_rule_xor(self, conn):
        b = B(conn)
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, project_operation_id, price_unit_id, is_active) "
              f"VALUES ('X',{ct},{op},{op},{unit},true)", frag="ck_lpr_op_xor")

    def test_m6_lprv_range_check(self, conn):
        rule_id = conn.execute(
            "INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, price_unit_id, is_active) "
            "VALUES ('RNG',%s,%s,%s,true) RETURNING id",
            (_ref(conn, "component_type_dict")[0], None or _ref(conn, "operation_type")[0], _ref(conn, "unit_of_measure")[0])).fetchone()[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, effective_to, is_current, occurred_at) "
              f"VALUES ({rule_id},1,100,'2026-06-01','2026-05-01',true,now())", frag="ck_lprv_range")

    def test_m8_rework_chargeability_check(self, conn):
        rc = _ref(conn, "reason_dictionary")[0]
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.rework_order(order_no, source_type, source_ref_type, source_ref_id, reason_category_id, chargeability, occurred_at) "
              f"VALUES ('BAD','inspection','task',0,{rc},'bogus',now())", frag="ck_rework_order_chargeability_values")

    def test_m4_current_partial_unique(self, conn):
        ct = _ref(conn, "component_type_dict")[0]
        conn.execute("INSERT INTO eng.component_type_process_template(component_type_id, version_no, status, is_current) "
                     "VALUES (%s,1,'active',true)", (ct,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO eng.component_type_process_template(component_type_id, version_no, status, is_current) "
                         "VALUES (%s,2,'active',true)", (ct,))


# ============ M5 标准模板→项目实例 ============
class TestAdoptStandardTemplate:
    def test_m5_adopt_copies_steps_and_is_one_way(self, conn):
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]
        op1 = b.op_type()
        op2 = conn.execute("SELECT id FROM ref.operation_type WHERE id <> %s ORDER BY id LIMIT 1", (op1,)).fetchone()[0]
        tpl = conn.execute(
            "INSERT INTO eng.component_type_process_template(component_type_id, version_no, status, is_current) "
            "VALUES (%s,1,'active',true) RETURNING id", (ct,)).fetchone()[0]
        conn.execute("INSERT INTO eng.component_type_process_step(template_id, step_no, operation_type_id, step_status) "
                     "VALUES (%s,1,%s,'active'),(%s,2,%s,'active')", (tpl, op1, tpl, op2))
        who = b.user()
        rt = adopt_standard_template(conn, standard_template_id=tpl, main_project_id=pid, adopted_by=who)
        # 来源追溯列
        row = conn.execute(
            "SELECT standard_template_id, standard_template_version, adopted_by FROM eng.route_template WHERE id=%s",
            (rt,)).fetchone()
        assert row[0] == tpl and row[1] == 1 and row[2] == who
        # 步骤被复制（2 行）
        n = conn.execute("SELECT count(*) FROM eng.route_template_step WHERE template_id=%s", (rt,)).fetchone()[0]
        assert n == 2
        # 单向：改项目步骤不影响标准模板
        conn.execute("UPDATE eng.route_template_step SET step_status='deprecated' WHERE template_id=%s AND step_no=1", (rt,))
        still = conn.execute("SELECT count(*) FROM eng.component_type_process_step WHERE template_id=%s AND step_status='active'",
                             (tpl,)).fetchone()[0]
        assert still == 2


# ============ M7 计价来源优先级 ============
class TestPriceResolution:
    def test_m7_project_overrides_base(self, conn):
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        _setup_base_rule(conn, ct, op, unit, price=100.0)
        # 项目价（project_operation_price）覆盖基础价
        po_id = conn.execute(
            "INSERT INTO eng.project_operation(main_project_id, project_operation_code, operation_type_id, is_active) "
            "VALUES (%s,'PO1',%s,true) RETURNING id", (pid, op)).fetchone()[0]
        conn.execute(
            "INSERT INTO eng.project_operation_price(project_operation_id, version_no, price, price_basis, effective_from, is_current, occurred_at) "
            "VALUES (%s,1,80,'piece',%s,true,%s)", (po_id, EFFECTIVE, NOW_DT))
        base = resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None, effective_date=EFFECTIVE)
        assert base == 100.0
        proj = resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                        project_operation_id_override=po_id, effective_date=EFFECTIVE)
        assert proj == 80.0  # 项目价覆盖基础价

    def test_m7_missing_price_is_none_not_zero(self, conn):
        b = B(conn)
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type()
        # 没有任何规则/项目价
        p = resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None, effective_date=EFFECTIVE)
        assert p is None


# ============ M8/M9 计价资格 + 单任务成本 ============
class TestChargeability:
    def test_m8_classify(self):
        # 第4轮：responsibility_kind 为权威来源
        # TEAM + 责任==执行（自责）→ non_chargeable
        assert classify_chargeability("TEAM", True, responsible_team_id=1, execute_team_id=1) == "non_chargeable"
        # NON_TEAM（外部责任）→ chargeable
        assert classify_chargeability("NON_TEAM", True) == "chargeable"
        # 正常作业不受返工判定影响
        assert classify_chargeability(None, False) == "chargeable"

    def test_m9_non_chargeable_amount_zero(self, conn):
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        ac, step = _build_component(conn, b, sid, ct, op)
        team = b.team()
        _setup_base_rule(conn, ct, op, unit, price=100.0)
        # 责任未确认（PENDING）→ 不可结算 → 金额 0
        res = compute_task_labor_cost(
            conn, component_type_id=ct, operation_type_id=op, team_id=team,
            effective_date=EFFECTIVE, quantity=2.0, responsibility_kind="PENDING", is_rework=True)
        assert res["chargeable"] is False and res["amount"] == 0.0

    def test_m9_missing_price_amount_none(self, conn):
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type()
        ac, step = _build_component(conn, b, sid, ct, op)
        team = b.team()
        res = compute_task_labor_cost(
            conn, component_type_id=ct, operation_type_id=op, team_id=team,
            effective_date=EFFECTIVE, quantity=1.0)  # 无价
        assert res["chargeable"] is True and res["amount"] is None  # MISSING_PRICE，绝不 0


# ============ M10 三个返工场景（测最终金额） ============
class TestReworkScenarios:
    def _base(self, conn):
        b = B(conn)
        pid, sid = b.project()
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        ac, step = _build_component(conn, b, sid, ct, op)
        teamA = b.team(); teamB = b.team()
        _setup_base_rule(conn, ct, op, unit, price=100.0)
        rc_qual = _reason(conn, 'quality')        # 班组责任原因 → 应 non_chargeable
        rc_nonqual = _reason(conn, 'material')     # 非班组责任原因 → 应 chargeable
        return b, ac, step, teamA, teamB, rc_qual, rc_nonqual

    def test_scenario_A_self_blame_A_counted_once(self, conn):
        """A 责任→A 返工（TEAM + 责任==执行）→ A 只计 1 次。"""
        b, ac, step, teamA, teamB, rc_qual, rc_nonqual = self._base(conn)
        t1 = _make_task(conn, ac, step, teamA)  # 正常作业，可计酬
        # A 自身责任：responsibility_kind=TEAM，责任班组=A，执行班组=A → 自责返工不计酬
        ro = _make_rework(conn, "pending", rc_qual, responsibility_kind="TEAM", responsible_team_id=teamA)
        t2 = _make_task(conn, ac, step, teamA, rework_of=t1, rework_order_id=ro, attempt=2)  # A 返工，不计酬
        ct = b._id("SELECT id FROM ref.component_type_dict LIMIT 1"); op = b.op_type()
        c1 = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamA,
                                    effective_date=EFFECTIVE, quantity=1.0)["amount"]
        c2 = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamA,
                                    effective_date=EFFECTIVE, quantity=1.0,
                                    responsibility_kind="TEAM", responsible_team_id=teamA, execute_team_id=teamA,
                                    is_rework=True)["amount"]
        # 正常 100；返工（自责非计酬）0 → A 合计 100（只计 1 次）
        assert c1 == 100.0
        assert c2 == 0.0

    def test_scenario_B_A_blame_B_rework_A1_B1(self, conn):
        """A 责任→B 返工（TEAM + 责任!=执行）→ A=1,B=1（B 执行方正常计酬）。"""
        b, ac, step, teamA, teamB, rc_qual, rc_nonqual = self._base(conn)
        t1 = _make_task(conn, ac, step, teamA)  # A 正常
        # A 责任：responsibility_kind=TEAM，责任班组=A，执行班组=B → B 计酬
        ro = _make_rework(conn, "pending", rc_nonqual, responsibility_kind="TEAM", responsible_team_id=teamA)
        t2 = _make_task(conn, ac, step, teamB, rework_of=t1, rework_order_id=ro, attempt=2)  # B 返工，计酬
        ct = b._id("SELECT id FROM ref.component_type_dict LIMIT 1"); op = b.op_type()
        a_cost = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamA,
                                         effective_date=EFFECTIVE, quantity=1.0)["amount"]
        b_cost = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamB,
                                         effective_date=EFFECTIVE, quantity=1.0,
                                         responsibility_kind="TEAM", responsible_team_id=teamA, execute_team_id=teamB,
                                         is_rework=True)["amount"]
        assert a_cost == 100.0 and b_cost == 100.0

    def test_scenario_C_design_change_B_normal(self, conn):
        """设计变更/材料/前道工序→B 返工（NON_TEAM）→ B 正常计（与 B 同口径）。"""
        b, ac, step, teamA, teamB, rc_qual, rc_nonqual = self._base(conn)
        t1 = _make_task(conn, ac, step, teamA)
        # 外部责任：responsibility_kind=NON_TEAM，无责任班组 → B 执行方计酬
        ro = _make_rework(conn, "pending", rc_nonqual, responsibility_kind="NON_TEAM")
        t2 = _make_task(conn, ac, step, teamB, rework_of=t1, rework_order_id=ro, attempt=2)
        ct = b._id("SELECT id FROM ref.component_type_dict LIMIT 1"); op = b.op_type()
        a_cost = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamA,
                                         effective_date=EFFECTIVE, quantity=1.0)["amount"]
        b_cost = compute_task_labor_cost(conn, component_type_id=ct, operation_type_id=op, team_id=teamB,
                                         effective_date=EFFECTIVE, quantity=1.0,
                                         responsibility_kind="NON_TEAM", execute_team_id=teamB,
                                         is_rework=True)["amount"]
        assert a_cost == 100.0 and b_cost == 100.0


# ============ M11 历史不可变（价格版本时间旅行） ============
class TestHistoryImmutable:
    def test_m11_price_version_time_travel(self, conn):
        b = B(conn)
        ct = _ref(conn, "component_type_dict")[0]; op = b.op_type(); unit = _ref(conn, "unit_of_measure")[0]
        rule_id = conn.execute(
            "INSERT INTO eng.labor_pricing_rule(rule_code, component_type_id, operation_type_id, price_unit_id, is_active) "
            "VALUES ('HIST',%s,%s,%s,true) RETURNING id", (ct, op, unit)).fetchone()[0]
        # 旧版本（2025 年有效）价格 100，已非当前
        conn.execute(
            "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, effective_to, is_current, occurred_at) "
            "VALUES (%s,1,100,'2025-01-01','2025-12-31',false,now())", (rule_id,))
        # 新版本（2026 年起有效）价格 200，当前
        conn.execute(
            "INSERT INTO eng.labor_pricing_rule_version(rule_id, version_no, unit_price, effective_from, is_current, occurred_at) "
            "VALUES (%s,2,200,'2026-01-01',true,now())", (rule_id,))
        # occurred_at=2025-06-01 应匹配旧版本 100（历史不被动新版本污染）
        old = resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                       effective_date=date(2025, 6, 1))
        new = resolve_labor_unit_price(conn, component_type_id=ct, operation_type_id=op, team_id=None,
                                       effective_date=date(2026, 6, 1))
        assert old == 100.0 and new == 200.0
