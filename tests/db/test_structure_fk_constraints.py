"""Phase 3 数据库级测试 A/B/C：结构完整性 / FK / 约束 + NB-3 幂等键分工。"""
import psycopg
import pytest
from conftest import ALL_SCHEMAS, fails, succeeds
from helpers import B

EXPECTED_PER_SCHEMA = {"aud": 13, "eng": 18, "imp": 5, "md": 20, "prod": 34,
                       "ref": 14, "ship": 14, "whs": 23}
EXPECTED_SEED = {"operation_type": 16, "inspection_type": 4, "exception_category": 7,
                 "acceptance_result": 4, "subproject_type": 4, "reason_dictionary": 12,
                 "unit_of_measure": 6, "code_rule": 12, "system_config": 4,
                 "component_type_dict": 6, "component_feature_dict": 8}


class TestAStructure:
    def test_a1_131_tables_in_8_schemas(self, conn):
        rows = conn.execute(
            "SELECT n.nspname, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = ANY(%s) GROUP BY 1", (ALL_SCHEMAS,)).fetchall()
        assert dict(rows) == EXPECTED_PER_SCHEMA
        assert sum(r[1] for r in rows) == 141

    def test_a2_22_enum_types(self, conn):
        n = conn.execute("SELECT count(*) FROM pg_type WHERE typtype = 'e' "
                         "AND typnamespace = 'public'::regnamespace AND typname LIKE 'enum_%'").fetchone()[0]
        assert n == 22

    def test_a3_seed_dictionaries(self, conn):
        for table, expected in EXPECTED_SEED.items():
            n = conn.execute(f"SELECT count(*) FROM ref.{table}").fetchone()[0]
            assert n == expected, f"ref.{table} 期望 {expected} 行，实际 {n}"
        assert conn.execute("SELECT count(*) FROM md.role").fetchone()[0] == 9


class TestBForeignKeys:
    def test_b1_total_fk_243(self, conn):
        # 本轮 c1 迁移给 prod.rework_order 新增 responsible_team_id FK(md.team)，FK 总数 242 → 243。
        n = conn.execute(
            "SELECT count(*) FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n2 ON n2.oid = c.relnamespace "
            "WHERE con.contype = 'f' AND n2.nspname = ANY(%s)", (ALL_SCHEMAS,)).fetchone()[0]
        assert n == 243

    def test_b2_deferred_cycle_fks_present(self, conn):
        """3 个 use_alter 循环 FK（autogenerate 不生成，迁移手工补）。"""
        pairs = [("prod", "actual_component", "qr_code_id"),
                 ("prod", "qr_code_registry", "actual_component_id"),
                 ("whs", "material_reservation", "consumed_by_ledger_id")]
        for sch, table, col in pairs:
            n = conn.execute(
                "SELECT count(*) FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n2 ON n2.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(con.conkey) "
                "WHERE con.contype='f' AND n2.nspname=%s AND c.relname=%s AND a.attname=%s",
                (sch, table, col)).fetchone()[0]
            assert n >= 1, f"缺少 FK: {sch}.{table}.{col}"

    def test_b3_all_fk_restrict(self, conn):
        """核心规则：无 ON DELETE CASCADE（0.2 设计总则）。"""
        n = conn.execute(
            "SELECT count(*) FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n2 ON n2.oid = c.relnamespace "
            "WHERE con.contype='f' AND n2.nspname = ANY(%s) AND con.confdeltype = 'c'",
            (ALL_SCHEMAS,)).fetchone()[0]
        assert n == 0, "存在 CASCADE 删除规则"


class TestCConstraints:
    def test_c1_pk_unique_check_counts(self, conn):
        base = ("FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
                "JOIN pg_namespace n2 ON n2.oid = c.relnamespace WHERE n2.nspname = ANY(%s)")
        pk = conn.execute(f"SELECT count(*) {base} AND con.contype='p'", (ALL_SCHEMAS,)).fetchone()[0]
        uq = conn.execute(f"SELECT count(*) {base} AND con.contype='u'", (ALL_SCHEMAS,)).fetchone()[0]
        ck = conn.execute(f"SELECT count(*) {base} AND con.contype='c'",
                          (ALL_SCHEMAS,)).fetchone()[0]
        assert pk == 141, f"PK 期望 141 实际 {pk}"
        assert uq == 100, f"UNIQUE 期望 100 实际 {uq}"
        # CHECK 期望 86 = 原 82 + c6 三个 rework_order 责任判定防旁路 CK
        #   (ck_rework_order_resp_kind_values / ck_rework_order_resp_team / ck_rework_order_pending_chargeable)
        # + c8 新增 1 个 ORANGE-3 一致性 CK (ck_rework_order_null_chargeable：NULL+chargeable 拒绝)。
        # （chargeability 三值 CK 为同名重建，不计新增；FK/UNIQUE/PK 数量均不变）
        assert ck == 86, f"CHECK 期望 86（原 82 + c6 三个 + c8 一个 ORANGE-3 CK） 实际 {ck}"

    def test_c2_nb3_action_key_unique(self, conn):
        """NB-3：action_key 业务动作幂等 = (task_id, action_key) UNIQUE。"""
        b = B(conn)
        _, sid = b.project()
        cli = b.list_item(sid)
        line = b.bom_line(cli)
        ac = b.component(sid, cli, "C1")
        step = b.route_step(conn.execute("SELECT id FROM md.main_project LIMIT 1").fetchone()[0])
        team = b.team()
        task = b.task(ac, step, team)
        b.report(task, ac, step, team, action_key="start")
        with pytest.raises(psycopg.errors.UniqueViolation):
            b.report(task, ac, step, team, action_key="start", client_token="retry-token")

    def test_c3_nb3_client_token_retry_idempotency(self, conn):
        """NB-3：client_token 网络幂等——同 token 不同 action_key 仍被拦截（返回首次结果由服务层做）。"""
        b = B(conn)
        _, sid = b.project()
        cli, line = b.list_item(sid), None
        line = b.bom_line(cli)
        ac = b.component(sid, cli, "C1")
        step = b.route_step(conn.execute("SELECT id FROM md.main_project LIMIT 1").fetchone()[0])
        team = b.team()
        task = b.task(ac, step, team)
        b.report(task, ac, step, team, action_key="start", client_token="tok-1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            b.report(task, ac, step, team, action_key="pause", client_token="tok-1")

    def test_c4_nb3_report_seq_not_identity(self, conn):
        """NB-3：report_seq 为展示序号可空可重复，不承担幂等身份。"""
        b = B(conn)
        _, sid = b.project()
        cli = b.list_item(sid)
        line = b.bom_line(cli)
        ac = b.component(sid, cli, "C1")
        step = b.route_step(conn.execute("SELECT id FROM md.main_project LIMIT 1").fetchone()[0])
        team = b.team()
        task = b.task(ac, step, team)
        b.report(task, ac, step, team, action_key="start", seq=1)
        b.report(task, ac, step, team, action_key="pause", seq=1)  # 同 seq 不同 action_key 合法

    def test_c5_nb5_batch_entry_rules(self, conn):
        """NB-5：批次入口 CHECK——receipt_acceptance 必须挂验收行；opening/manual 必须审批留痕。"""
        b = B(conn)
        mat, sup = b.material(), b.supplier()
        now = "now()"
        # receipt_acceptance 缺 receipt_item_id → 拒绝
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO whs.material_batch(material_id, factory_batch_no, heat_no, supplier_id, "
              f"grade_snapshot, spec_snapshot, original_weight, batch_source, occurred_at) "
              f"VALUES ({mat}, 'FBX', 'H-X', {sup}, 'Q355B', 't10', 100, 'receipt_acceptance', {now})",
              frag="ck_material_batch_entry_rules")
        # opening 缺审批 → 拒绝
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO whs.material_batch(material_id, factory_batch_no, heat_no, supplier_id, "
              f"grade_snapshot, spec_snapshot, original_weight, batch_source, source_ref, occurred_at) "
              f"VALUES ({mat}, 'FBY', 'H-Y', {sup}, 'Q355B', 't10', 100, 'opening', '期初', {now})",
              frag="ck_material_batch_entry_rules")
        # opening 带审批留痕 → 通过
        approver = b.user()
        succeeds(conn,
                 f"INSERT INTO whs.material_batch(material_id, factory_batch_no, heat_no, supplier_id, "
                 f"grade_snapshot, spec_snapshot, original_weight, batch_source, source_ref, "
                 f"approved_by, approved_at, occurred_at) "
                 f"VALUES ({mat}, 'FBZ', 'H-Z', {sup}, 'Q355B', 't10', 100, 'opening', '期初导入', "
                 f"{approver}, {now}, {now})")

    def test_c6_consumption_source_required(self, conn):
        """约束 21：source_kind 判别 + 双列条件非空。"""
        b = B(conn)
        _, sid = b.project()
        cli, line = b.list_item(sid), None
        line = b.bom_line(cli)
        ac = b.component(sid, cli, "C1")
        part = b.part(ac, line)
        now = "now()"
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO whs.material_consumption(part_instance_id, source_kind, occurred_at) "
              f"VALUES ({part}, 'raw_batch', {now})",
              frag="ck_material_consumption_source_required")

    def test_c7_make_type_supplier_check(self, conn):
        """约束 27：outsource ⇒ supplier 非空；inhouse ⇒ 必空。"""
        b = B(conn)
        pid, sid = b.project()
        cli = b.list_item(sid)
        line = b.bom_line(cli)
        ac = b.component(sid, cli, "C1")
        step = b.route_step(pid)
        team = b.team()
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO prod.production_task(actual_component_id, route_template_step_id, "
              f"execute_team_id, make_type) VALUES ({ac}, {step}, {team}, 'outsource')",
              frag="ck_production_task_make_type_supplier")

    def test_c8_stock_guardrails(self, conn):
        """库存底线：ledger qty<>0、balance 非负、surplus 行必须挂 surplus_id。"""
        b = B(conn)
        mat, sup = b.material(), b.supplier()
        batch = b.batch(mat, sup, "H-1")
        _, loc = b.wh_loc()
        now = "now()"
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
              f"qty_weight, occurred_at) VALUES ('stock_in', {batch}, {loc}, 0, {now})",
              frag="ck_stock_ledger_qty_weight_nonzero")
        b.stock_in(batch, loc, 50.0)
        conn.commit()
        fails(conn, psycopg.errors.CheckViolation,
              f"UPDATE whs.stock_balance SET weight_kg = weight_kg - 60 "
              f"WHERE material_batch_id={batch} AND storage_location_id={loc}",
              frag="ck_stock_balance_weight_non_negative")
        fails(conn, psycopg.errors.CheckViolation,
              f"INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
              f"qty_weight, occurred_at) VALUES ('surplus_in', {batch}, {loc}, 10, {now})",
              frag="ck_stock_ledger_surplus_required")

    def test_c9_material_code_unique_and_surplus_self_parent(self, conn):
        b = B(conn)
        code = b.material()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO md.material(material_code, name, category, grade, specification, unit_id) "
                         "SELECT material_code, 'x', 'plate', 'Q355B', 't10', unit_id FROM md.material WHERE id=%s",
                         (code,))
        conn.rollback()
        mat, sup = b.material(), b.supplier()
        batch = b.batch(mat, sup, "H-SP")
        sp = b.surplus(batch, 10.0)
        fails(conn, psycopg.errors.CheckViolation,
              f"UPDATE whs.surplus_material SET parent_surplus_id = id WHERE id = {sp}",
              frag="ck_surplus_material_no_self_parent")
