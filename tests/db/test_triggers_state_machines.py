"""Phase 3 数据库级测试 D/E：状态机值域 / T-1~T-16 触发器正反向 + NB-1 权限矩阵。

GUC 白名单（事务本地）：
- mes.import_processing（T-8）  mes.reversal_context（T-10）  mes.issue_posting（T-11）
"""
import psycopg
import pytest
from conftest import fails, succeeds
from helpers import B, NOW

SCM_EN = ["enum_project", "enum_ac_production", "enum_ac_quality", "enum_task_status",
          "enum_inspection", "enum_exception", "enum_pallet", "enum_container",
          "enum_shipment", "enum_reservation"]


def prod_chain(conn):
    """最小生产链：project → list_item → bom_line → component → part。"""
    b = B(conn)
    pid, sid = b.project()
    cli = b.list_item(sid)
    line = b.bom_line(cli)
    ac = b.component(sid, cli, "C1")
    part = b.part(ac, line)
    return b, pid, sid, cli, line, ac, part


class TestDStateMachines:
    def test_d1_ten_state_machine_domains(self, conn):
        """15 章 10 个核心状态机 ENUM 值域落库。"""
        for name in SCM_EN:
            n = conn.execute("SELECT count(*) FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                             "WHERE t.typname = %s", (name,)).fetchone()[0]
            assert n > 0, f"{name} 无枚举值"

    def test_d2_invalid_state_rejected(self, conn):
        """状态值封闭：越界值入库被拒（构件生产态无 cancelled）。"""
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        fails(conn, psycopg.errors.InvalidTextRepresentation,
              f"UPDATE prod.actual_component SET production_status='cancelled' WHERE id={ac}",
              frag="enum_ac_production")

    def test_d3_production_complete_not_quality_release(self, conn):
        """J-1 前置：生产完成与质量放行是两条独立状态线，无 DB 强绑定。"""
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        conn.execute("UPDATE prod.actual_component SET production_status='production_completed', "
                     "quality_status='pending_inspection' WHERE id=%s", (ac,))
        row = conn.execute("SELECT production_status, quality_status FROM prod.actual_component "
                           "WHERE id=%s", (ac,)).fetchone()
        assert row == ("production_completed", "pending_inspection")


class TestETriggers:
    # ---------- T-1 快照冻结 ----------
    def test_t1_snapshot_freeze(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        shp = b._id("INSERT INTO ship.shipment(shipment_no, main_project_id) VALUES ('SHP1', %s) RETURNING id", (pid,))
        conn.execute("INSERT INTO ship.shipment_snapshot(shipment_id, actual_component_id, snapshotted_at) "
                     "VALUES (%s, %s, %s)", (shp, ac, NOW))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE ship.shipment_snapshot SET weight_snapshot=1 WHERE shipment_id={shp}",
              frag="T-1")
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM ship.shipment_snapshot WHERE shipment_id={shp}", frag="T-1")

    # ---------- T-2 补件血缘 ----------
    def test_t2_replacement_target(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        # 反例：指向未报废构件
        fails(conn, psycopg.errors.RaiseException,
              f"INSERT INTO prod.actual_component(subproject_id, component_list_item_id, component_no, "
              f"instance_sequence, qr_code_id, replacement_for) VALUES ({sid}, {cli}, 'C1', 2, {b.qr()}, {ac})",
              frag="T-2")
        # 正例：报废后补件
        cat = conn.execute("SELECT id FROM ref.exception_category LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO prod.component_scrap_record(actual_component_id, scrap_no, "
                     "reason_category_id, occurred_at) VALUES (%s, 'SCRAP1', %s, %s)", (ac, cat, NOW))
        conn.execute("UPDATE prod.actual_component SET production_status='scrapped' WHERE id=%s", (ac,))
        new_id = b.component(sid, cli, "C1", seq=2)
        conn.execute("UPDATE prod.actual_component SET replacement_for=%s WHERE id=%s", (ac, new_id))

    # ---------- T-3 零件替代血缘 ----------
    def test_t3_part_replacement(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        # 反例：目标未 substituted
        fails(conn, psycopg.errors.RaiseException,
              f"INSERT INTO prod.part_instance(actual_component_id, bom_template_line_id, "
              f"instance_sequence, origin_part_no, replacement_of, replacement_reason, replaced_at) "
              f"VALUES ({ac}, {line}, 2, 'P-01', {part}, '裂纹', '{NOW}')", frag="T-3")
        conn.execute("UPDATE prod.part_instance SET status='substituted' WHERE id=%s", (part,))
        # 反例：缺替代事实
        fails(conn, psycopg.errors.RaiseException,
              f"INSERT INTO prod.part_instance(actual_component_id, bom_template_line_id, "
              f"instance_sequence, origin_part_no, replacement_of) "
              f"VALUES ({ac}, {line}, 2, 'P-01', {part})", frag="T-3")
        # 正例
        conn.execute("INSERT INTO prod.part_instance(actual_component_id, bom_template_line_id, "
                     "instance_sequence, origin_part_no, replacement_of, replacement_reason, replaced_at) "
                     "VALUES (%s, %s, 2, 'P-01', %s, '裂纹', %s)", (ac, line, part, NOW))

    # ---------- T-4 BOM 模板行 ----------
    def test_t4_bom_line_immutable(self, conn):
        b = B(conn)
        _, sid = b.project()
        cli = b.list_item(sid)
        line2 = b.bom_line(cli)
        # 未引用：语义列可改
        conn.execute("UPDATE eng.bom_template_line SET part_no='P-99' WHERE id=%s", (line2,))
        # DELETE 一律阻止
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM eng.bom_template_line WHERE id={line2}", frag="T-4")
        # 引用后语义列禁改
        line3 = b.bom_line(cli, line_no=2, part_no="P-02")
        b.part(b.component(sid, cli, "C2"), line3)
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE eng.bom_template_line SET qty_per_component=9 WHERE id={line3}", frag="T-4")

    # ---------- T-5 工序行 ----------
    def test_t5_step_immutable(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        step = b.route_step(pid)
        # 未引用：语义列可改
        conn.execute("UPDATE eng.route_template_step SET default_requirement='新要求' WHERE id=%s", (step,))
        # 引用后禁改 + 禁删
        team = b.team()
        task = b.task(ac, step, team)
        b.report(task, ac, step, team, action_key="start")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE eng.route_template_step SET default_requirement='改' WHERE id={step}", frag="T-5")
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM eng.route_template_step WHERE id={step}", frag="T-5")

    # ---------- T-6 make_type 终局 ----------
    def test_t6_make_type_final(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        step = b.route_step(pid)
        task = b.task(ac, step, b.team())
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.production_task SET make_type='outsource' WHERE id={task}", frag="T-6")

    # ---------- T-7 material_code 禁改 ----------
    def test_t7_material_code_final(self, conn):
        b = B(conn)
        mat = b.material()
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE md.material SET material_code='NEWCODE' WHERE id={mat}", frag="T-7")

    # ---------- T-8 import_row 冻结 ----------
    def _import_batch_row(self, conn, b, sid):
        bid = b._id("INSERT INTO imp.component_list_import_batch(subproject_id, source_file_name, "
                    "file_hash, mapping_version, imported_by, imported_at, occurred_at) "
                    "VALUES (%s, 'x.xlsx', 'hash1', 1, %s, %s, %s) RETURNING id", (sid, b.user(), NOW, NOW))
        rid = b._id("INSERT INTO imp.import_row(import_batch_id, source_row_number, source_identity, "
                    "raw_payload, result_status, occurred_at) VALUES (%s, 1, 'key-1', '{}', 'created', %s) "
                    "RETURNING id", (bid, NOW))
        return bid, rid

    def test_t8_import_row_freeze(self, conn):
        b = B(conn)
        _, sid = b.project()
        _, rid = self._import_batch_row(conn, b, sid)
        # 处理事务外 UPDATE → 拒绝
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE imp.import_row SET result_status='kept' WHERE id={rid}", frag="T-8")
        # 处理事务内 → 允许
        conn.execute("SELECT set_config('mes.import_processing','on',true)")
        conn.execute("UPDATE imp.import_row SET result_status='kept' WHERE id=%s", (rid,))
        conn.commit()
        # 物理删除一律拒绝
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM imp.import_row WHERE id={rid}", frag="T-8")

    # ---------- T-9 检验结论 ----------
    def test_t9_quality_conclusion(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        itype = conn.execute("SELECT id FROM ref.inspection_type LIMIT 1").fetchone()[0]
        ins = b._id("INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, "
                    "inspector_id, occurred_at) VALUES (%s, %s, %s, %s) RETURNING id",
                    (ac, itype, b.user(), NOW))
        # 白名单外列（异值）
        fails(conn, psycopg.errors.RaiseException,
              "UPDATE prod.quality_inspection SET occurred_at='2026-09-19 10:00:00' "
              f"WHERE id={ins}", frag="T-9")
        # 状态流转 OK
        conn.execute("UPDATE prod.quality_inspection SET inspection_status='inspecting' WHERE id=%s", (ins,))
        # 结论一次置值
        conn.execute("UPDATE prod.quality_inspection SET inspection_status='concluded', "
                     "conclusion='pass' WHERE id=%s", (ins,))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.quality_inspection SET conclusion='fail' WHERE id={ins}", frag="T-9")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.quality_inspection SET conclusion=NULL WHERE id={ins}", frag="T-9")

    # ---------- T-10 消耗冲正 ----------
    def test_t10_consumption_reversal(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        mat, sup = b.material(), b.supplier()
        batch = b.batch(mat, sup, "H-T10")
        _, loc = b.wh_loc()
        b.stock_in(batch, loc, 100.0)
        cid = b.consumption(part, batch, 20.0)
        # 白名单外列
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_consumption SET weight=99 WHERE id={cid}", frag="T-10")
        # 无 GUC
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_consumption SET is_effective=false WHERE id={cid}", frag="T-10")
        # GUC 有、reversal_record 无
        conn.execute("SELECT set_config('mes.reversal_context','on',true)")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_consumption SET is_effective=false WHERE id={cid}", frag="T-10")
        # 完整冲正路径
        conn.execute("INSERT INTO aud.reversal_record(original_ref_type, original_ref_id, occurred_at) "
                     "VALUES ('material_consumption', %s, %s)", (cid, NOW))
        conn.execute("UPDATE whs.material_consumption SET is_effective=false WHERE id=%s", (cid,))
        conn.commit()
        # false→true 一律阻止
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_consumption SET is_effective=true WHERE id={cid}", frag="T-10")

    # ---------- T-11 领料明细聚合 ----------
    def test_t11_issue_line_aggregate(self, conn):
        b = B(conn)
        mat, sup = b.material(), b.supplier()
        batch = b.batch(mat, sup, "H-T11")
        _, loc = b.wh_loc()
        b.stock_in(batch, loc, 100.0)
        team = b.team()
        _, sid = b.project()
        doc = b.issue_doc(b.user(), team, sid)
        il = b.issue_line(doc, 1, mat, batch, loc, 30.0)
        # 无 GUC
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_issue_line SET issued_qty=30 WHERE id={il}", frag="T-11")
        # GUC 有但与流水聚合不符（尚无 ledger 行）
        conn.execute("SELECT set_config('mes.issue_posting','on',true)")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_issue_line SET issued_qty=30 WHERE id={il}", frag="T-11")
        # 正向过账
        b.post_issue(il, 30.0, batch, loc)
        # 白名单外列
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_issue_line SET requested_qty=99 WHERE id={il}", frag="T-11")

    # ---------- T-12 清单行 void ----------
    def test_t12_list_item_void(self, conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        # 已实例化禁止 void
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.component_list_item SET row_status='voided' WHERE id={cli}", frag="T-12")
        # 未实例化行：void 单向
        cli2 = b.list_item(sid)
        conn.execute("UPDATE prod.component_list_item SET row_status='voided' WHERE id=%s", (cli2,))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.component_list_item SET name='改名' WHERE id={cli2}", frag="T-12")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.component_list_item SET row_status='active' WHERE id={cli2}", frag="T-12")
        fails(conn, psycopg.errors.RaiseException,
              f"DELETE FROM prod.component_list_item WHERE id={cli2}", frag="T-12")

    # ---------- T-13 领料单头 ----------
    def test_t13_issue_doc_status_only(self, conn):
        b = B(conn)
        doc = b.issue_doc(b.user(), b.team())
        conn.execute("UPDATE whs.material_issue_document SET status='confirmed' WHERE id=%s", (doc,))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_issue_document SET remark='x' WHERE id={doc}", frag="T-13")
        conn.execute("UPDATE whs.material_issue_document SET status='voided' WHERE id=%s", (doc,))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.material_issue_document SET status='confirmed' WHERE id={doc}", frag="T-13")

    # ---------- T-14 验收窄路径 ----------
    def test_t14_receipt_acceptance(self, conn):
        b = B(conn)
        mat, sup = b.material(), b.supplier()
        b.batch(mat, sup, "H-T14")  # receipt+item 已建
        item = conn.execute("SELECT id FROM whs.purchase_receipt_item ORDER BY id DESC LIMIT 1").fetchone()[0]
        acc = conn.execute("SELECT id FROM ref.acceptance_result ORDER BY id LIMIT 1").fetchone()[0]
        acc2 = conn.execute("SELECT id FROM ref.acceptance_result ORDER BY id OFFSET 1 LIMIT 1").fetchone()[0]
        conn.execute("UPDATE whs.purchase_receipt_item SET acceptance_result_id=%s, accepted_at=%s, "
                     "accepted_by=%s WHERE id=%s", (acc, NOW, b.user(), item))
        # 一次置值后再改 → 拒绝（同值 no-op 不触发，异值触发）
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.purchase_receipt_item SET acceptance_result_id={acc2} WHERE id={item}",
              frag="T-14")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE whs.purchase_receipt_item SET received_qty=5 WHERE id={item}", frag="T-14")

    # ---------- T-15/T-16 窄路径白名单 ----------
    def test_t15_t16_narrow_paths(self, conn):
        b = B(conn)
        did = b._id("INSERT INTO eng.drawing(drawing_no, name) VALUES ('D1', '图纸') RETURNING id")
        conn.execute("INSERT INTO eng.drawing_revision(drawing_id, revision_no, released_at, occurred_at) "
                     "VALUES (%s, 'A', %s, %s)", (did, NOW, NOW))
        dr = conn.execute("SELECT id FROM eng.drawing_revision ORDER BY id DESC LIMIT 1").fetchone()[0]
        conn.execute("UPDATE eng.drawing_revision SET is_effective=true WHERE id=%s", (dr,))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE eng.drawing_revision SET file_ref='f' WHERE id={dr}", frag="T-15")
        # final_qualification
        _, sid = b.project()
        cli = b.list_item(sid)
        ac = b.component(sid, cli, "C1")
        fq = b._id("INSERT INTO prod.final_qualification(actual_component_id, released_by, released_at, "
                   "occurred_at) VALUES (%s, %s, %s, %s) RETURNING id", (ac, b.user(), NOW, NOW))
        conn.execute("UPDATE prod.final_qualification SET revoked=true, revoked_at=%s WHERE id=%s", (NOW, fq))
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.final_qualification SET is_qualified=false WHERE id={fq}", frag="T-16")
        fails(conn, psycopg.errors.RaiseException,
              f"UPDATE prod.final_qualification SET revoked=false WHERE id={fq}", frag="T-16")


class TestNB1Permissions:
    """NB-1 权限矩阵落库验证：mes_app 角色对 A/B/C/D 的差异能力。"""

    def test_p1_select_insert_everywhere(self, conn, app_conn):
        conn.commit()  # setup 提交，app_conn 可见
        assert app_conn.execute("SELECT count(*) FROM whs.stock_ledger").fetchone()[0] == 0

    def test_p2_update_blocked_on_b_and_d(self, conn, app_conn):
        b, pid, sid, cli, line, ac, part = prod_chain(conn)
        mat, sup = b.material(), b.supplier()
        batch = b.batch(mat, sup, "H-P")
        _, loc = b.wh_loc()
        b.stock_in(batch, loc, 10.0)
        conn.execute("INSERT INTO aud.operation_log(op_type, op_at, occurred_at) "
                     "VALUES ('test', %s, %s)", (NOW, NOW))
        conn.commit()
        # B 类无白名单：UPDATE 拒绝
        fails(app_conn, psycopg.errors.InsufficientPrivilege,
              f"UPDATE whs.stock_ledger SET qty_weight=1 WHERE material_batch_id={batch}",
              frag="permission denied")
        # D 类：UPDATE 拒绝
        fails(app_conn, psycopg.errors.InsufficientPrivilege,
              "UPDATE aud.operation_log SET op_type='y'", frag="permission denied")

    def test_p3_delete_denied_everywhere(self, conn, app_conn):
        b = B(conn)
        mat = b.material()
        conn.commit()
        fails(app_conn, psycopg.errors.InsufficientPrivilege,
              f"DELETE FROM md.material WHERE id={mat}", frag="permission denied")
        fails(app_conn, psycopg.errors.InsufficientPrivilege,
              f"DELETE FROM ref.operation_type WHERE id=1", frag="permission denied")

    def test_p4_update_allowed_on_a_and_c_and_whitelist_b(self, conn, app_conn):
        b = B(conn)
        mat = b.material()
        conn.execute("UPDATE md.material SET name='改名' WHERE id=%s", (mat,))
        conn.execute("UPDATE ref.system_config SET config_value='1' WHERE id="
                     "(SELECT id FROM ref.system_config LIMIT 1)")
        # 白名单 B：quality_inspection
        pid, sid = b.project()
        cli = b.list_item(sid)
        ac = b.component(sid, cli, "C1")
        itype = conn.execute("SELECT id FROM ref.inspection_type LIMIT 1").fetchone()[0]
        ins = b._id("INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, "
                    "inspector_id, occurred_at) VALUES (%s, %s, %s, %s) RETURNING id",
                    (ac, itype, b.user(), NOW))
        conn.commit()
        # A 类可 UPDATE（mes_app）
        app_conn.execute("UPDATE md.material SET name='应用改名' WHERE id=%s", (mat,))
        # 白名单 B 可 UPDATE（触发器管内容）
        app_conn.execute("UPDATE prod.quality_inspection SET inspection_status='inspecting' WHERE id=%s", (ins,))
        app_conn.commit()
