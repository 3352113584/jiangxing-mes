"""H 组仓库数量守恒 + J 组质量/生产测试（数据库级）。

H（任务书 H）：
- 到货车次登记不产生任何库存事实（约束 32）；验收生成批次同样不产生库存事实；
- 一采购单 → 多车次 → 一车次多材料明细 → 多 Heat 批次；同供应商同 Heat 唯一；
- 核心守恒：入库→领料→直接消耗→退料→余料入池→冲正 全链后
  余额 == 符号映射账行合计 == 85（领料/消耗/冲正不重复计算）。

J（任务书 J）：
- 生产完成 ≠ 质量放行（放行=独立 final_qualification 事实；当前放行部分唯一）；
- 返工不重复增加需求（需求=批次快照，返工新任务不新增需求行，重复需求行结构拒绝）；
- 返工检验走 attempt 递增（同构件同类型同 attempt 唯一）。
"""
import psycopg
import pytest

from conftest import fails
from helpers import B, NOW


# ============ H-1 到货车次登记无库存事实 ============

def test_h1_trip_registration_no_stock_facts(conn):
    b = B(conn)
    m = b.material()
    sup = b.supplier()
    user = b.user()

    po = conn.execute("INSERT INTO whs.purchase_order(po_no, supplier_id, order_date, status, created_at) "
                      "VALUES ('PO-H1', %s, %s, 'confirmed', %s) RETURNING id", (sup, NOW, NOW)).fetchone()[0]
    conn.execute("INSERT INTO whs.purchase_order_item(order_id, line_no, material_id, qty, weight, created_at) "
                 "VALUES (%s, 1, %s, 10, 500, %s)", (po, m, NOW))
    rid = conn.execute("INSERT INTO whs.purchase_receipt(receipt_no, purchase_order_id, trip_no, arrived_at, "
                       "received_by, occurred_at) VALUES ('RC-H1-1', %s, 'TRIP-1', %s, %s, %s) RETURNING id",
                       (po, NOW, user, NOW)).fetchone()[0]
    ri = conn.execute("INSERT INTO whs.purchase_receipt_item(receipt_id, line_no, material_id, received_qty, "
                      "received_weight, occurred_at) VALUES (%s, 1, %s, 10, 500, %s) RETURNING id",
                      (rid, m, NOW)).fetchone()[0]

    # 验收事务内按合格行生成批次（默认唯一入口）——登记与验收仍无库存事实
    conn.execute("INSERT INTO whs.material_batch(material_id, material_code_snapshot, factory_batch_no, heat_no, "
                 "supplier_id, grade_snapshot, spec_snapshot, original_weight, batch_source, receipt_item_id, "
                 "occurred_at) VALUES (%s, %s, 'FB-H1', 'H-001', %s, 'Q355B', 't10', 500, "
                 "'receipt_acceptance', %s, %s)", (m, "MC-H1", sup, ri, NOW))

    n_ledger = conn.execute("SELECT count(*) FROM whs.stock_ledger").fetchone()[0]
    n_balance = conn.execute("SELECT count(*) FROM whs.stock_balance").fetchone()[0]
    assert n_ledger == 0 and n_balance == 0, "约束 32：车次登记/验收不产生库存事实，入库上架才有账"


# ============ H-2 一 PO 多车次 + 多 Heat ============

def test_h2_one_po_multiple_trips_multi_heat(conn):
    b = B(conn)
    m = b.material()
    sup = b.supplier()
    user = b.user()

    po = conn.execute("INSERT INTO whs.purchase_order(po_no, supplier_id, order_date, status, created_at) "
                      "VALUES ('PO-H2', %s, %s, 'confirmed', %s) RETURNING id", (sup, NOW, NOW)).fetchone()[0]
    conn.execute("INSERT INTO whs.purchase_order_item(order_id, line_no, material_id, qty, weight, created_at) "
                 "VALUES (%s, 1, %s, 30, 1500, %s)", (po, m, NOW))

    # 验收事务内按合格行生成批次（挂到本 PO 车次明细）
    def batch_on(ri, heat, fb):
        return conn.execute(
            "INSERT INTO whs.material_batch(material_id, material_code_snapshot, factory_batch_no, heat_no, "
            "supplier_id, grade_snapshot, spec_snapshot, original_weight, batch_source, receipt_item_id, "
            "occurred_at) VALUES (%s, %s, %s, %s, %s, 'Q355B', 't10', 100, 'receipt_acceptance', %s, %s) "
            "RETURNING id", (m, "MC-H2", fb, heat, sup, ri, NOW)).fetchone()[0]

    rid1 = conn.execute("INSERT INTO whs.purchase_receipt(receipt_no, purchase_order_id, trip_no, arrived_at, "
                        "received_by, occurred_at) VALUES ('RC-H2-1', %s, 'TRIP-1', %s, %s, %s) RETURNING id",
                        (po, NOW, user, NOW)).fetchone()[0]
    ri1 = conn.execute("INSERT INTO whs.purchase_receipt_item(receipt_id, line_no, material_id, received_qty, "
                       "received_weight, occurred_at) VALUES (%s, 1, %s, 1, 100, %s) RETURNING id",
                       (rid1, m, NOW)).fetchone()[0]
    b1 = batch_on(ri1, "H-A", "FB-H2A")

    rid2 = conn.execute("INSERT INTO whs.purchase_receipt(receipt_no, purchase_order_id, trip_no, arrived_at, "
                        "received_by, occurred_at) VALUES ('RC-H2-2', %s, 'TRIP-2', %s, %s, %s) RETURNING id",
                        (po, NOW, user, NOW)).fetchone()[0]
    ri2 = conn.execute("INSERT INTO whs.purchase_receipt_item(receipt_id, line_no, material_id, received_qty, "
                       "received_weight, occurred_at) VALUES (%s, 1, %s, 1, 100, %s) RETURNING id",
                       (rid2, m, NOW)).fetchone()[0]
    ri3 = conn.execute("INSERT INTO whs.purchase_receipt_item(receipt_id, line_no, material_id, received_qty, "
                       "received_weight, occurred_at) VALUES (%s, 2, %s, 1, 100, %s) RETURNING id",
                       (rid2, m, NOW)).fetchone()[0]
    b2 = batch_on(ri2, "H-B", "FB-H2B")
    b3 = batch_on(ri3, "H-C", "FB-H2C")

    n_trips = conn.execute("SELECT count(*) FROM whs.purchase_receipt WHERE purchase_order_id=%s", (po,)).fetchone()[0]
    heats = [r[0] for r in conn.execute(
        "SELECT heat_no FROM whs.material_batch WHERE id IN (%s,%s,%s) ORDER BY heat_no", (b1, b2, b3))]
    assert n_trips == 2, "一 PO 多车次"
    assert heats == ["H-A", "H-B", "H-C"], "一车次多明细多 Heat，各 Heat 独立批次"

    # 同供应商同 Heat 不允许重复建批（Heat 追溯锚点唯一）
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO whs.material_batch(material_id, material_code_snapshot, factory_batch_no, heat_no, "
          "supplier_id, grade_snapshot, spec_snapshot, original_weight, batch_source, receipt_item_id, "
          "occurred_at) VALUES (%s, %s, 'FB-H2X', 'H-A', %s, 'Q355B', 't10', 100, 'receipt_acceptance', %s, %s)",
          (m, "MC-H2", sup, ri1, NOW), frag="uq_material_batch_supplier_heat_no")


# ============ H-3 核心数量守恒 ============

def test_h3_warehouse_quantity_conservation(conn):
    b = B(conn)
    pid, sid = b.project()
    m = b.material()
    sup = b.supplier()
    user = b.user()
    team = b.team()
    _, lid = b.wh_loc()

    # 1) 入库上架 100
    bid = b.batch(m, sup, "H-CON")
    b.stock_in(bid, lid, 100.0)

    # 2) 领料 30（单据行 + 过账账行 + 余额扣减）
    doc = b.issue_doc(user, team, sid)
    line = b.issue_line(doc, 1, m, bid, lid, 30)
    b.post_issue(line, 30, bid, lid)

    # 3) 直接消耗 20（消耗事实 + consumption_id 账行——不出第二笔独立扣账）
    cli = b.list_item(sid)
    bl = b.bom_line(cli)
    ac = b.component(sid, cli, "CON")
    part = b.part(ac, bl)
    cid = b.consumption(part, bid, 20.0)
    cons_row = conn.execute(
        "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, qty_weight, "
        "consumption_id, occurred_at) VALUES ('issue', %s, %s, 20, %s, %s) RETURNING id",
        (bid, lid, cid, NOW)).fetchone()[0]
    conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg - 20 "
                 "WHERE material_batch_id=%s AND storage_location_id=%s", (bid, lid))

    # 4) 退料 +5（独立 movement_type='return'，非负数领料行）
    b.return_material(bid, lid, 5.0)

    # 5) 余料入池 +10（surplus_in 强制 surplus_id）
    sp = b.surplus(bid, 10.0)
    b.surplus_in(sp, bid, lid, 10.0)

    # 6) 冲正消耗 20（reversal_record + 反向账行 qty=-20 + is_effective 翻转 + 余额回补）
    b.reversal(cid, cons_row, bid, lid, 20.0)

    # —— 守恒断言 ——
    assert b.balance(bid, lid) == pytest.approx(85.0), "100-30-20+5+10+20=85"

    # 通用守恒式：入库方向（stock_in/return/surplus_in/count_gain）取 +qty，
    # 出库方向（issue/surplus_issue/count_loss）取 -qty；冲正行 qty 反号自然参与同一公式。
    signed_total = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN movement_type IN ('stock_in','return','surplus_in','count_gain') "
        "THEN qty_weight ELSE -qty_weight END), 0) FROM whs.stock_ledger "
        "WHERE material_batch_id=%s AND storage_location_id=%s", (bid, lid)).fetchone()[0]
    assert float(signed_total) == pytest.approx(85.0), "余额 == 符号映射账行合计（无重复计算）"

    # 领料行聚合一致（T-11 语义）：issue_line 关联账行幅值合计 = issued_qty（qty_weight 存正幅值）
    agg = conn.execute("SELECT COALESCE(SUM(qty_weight),0) FROM whs.stock_ledger WHERE issue_line_id=%s",
                       (line,)).fetchone()[0]
    issued = conn.execute("SELECT issued_qty FROM whs.material_issue_line WHERE id=%s", (line,)).fetchone()[0]
    assert float(agg) == pytest.approx(float(issued)), "领料账行与 issued_qty 聚合一致"

    # 消耗冲正后失效，冲正记录恰一份
    eff = conn.execute("SELECT is_effective FROM whs.material_consumption WHERE id=%s", (cid,)).fetchone()[0]
    n_rev = conn.execute("SELECT count(*) FROM aud.reversal_record WHERE original_ref_type='material_consumption' "
                         "AND original_ref_id=%s", (cid,)).fetchone()[0]
    assert eff is False and n_rev == 1

    # 消耗路径账行只有一笔原始 + 一笔反向（不与领料重复扣账）
    n_cons_rows = conn.execute("SELECT count(*) FROM whs.stock_ledger WHERE consumption_id=%s", (cid,)).fetchone()[0]
    n_corr_rows = conn.execute("SELECT count(*) FROM whs.stock_ledger WHERE correction_of_id=%s",
                               (cons_row,)).fetchone()[0]
    assert n_cons_rows == 1 and n_corr_rows == 1


# ============ J-1 生产完成 ≠ 质量放行 ============

def test_j1_production_complete_not_quality_release(conn):
    b = B(conn)
    pid, sid = b.project()
    team = b.team()
    cli = b.list_item(sid)
    ac = b.component(sid, cli, "J1")
    step = b.route_step(pid)
    task = b.task(ac, step, team)

    # 生产完成（任务完结 + 构件状态推进）——但无任何放行事实
    conn.execute("UPDATE prod.production_task SET status='completed', actual_end=%s WHERE id=%s", (NOW, task))
    conn.execute("UPDATE prod.actual_component SET production_status='production_completed' WHERE id=%s", (ac,))
    n_fq = conn.execute("SELECT count(*) FROM prod.final_qualification WHERE actual_component_id=%s", (ac,)).fetchone()[0]
    assert n_fq == 0, "生产完成 ≠ 质量放行"

    # 检验登记未出结论：仍不放行
    itype = conn.execute("SELECT id FROM ref.inspection_type ORDER BY id LIMIT 1").fetchone()[0]
    inspector = b.user()
    insp = conn.execute("INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, "
                        "inspector_id, occurred_at) VALUES (%s, %s, %s, %s) RETURNING id",
                        (ac, itype, inspector, NOW)).fetchone()[0]
    n_fq = conn.execute("SELECT count(*) FROM prod.final_qualification WHERE actual_component_id=%s", (ac,)).fetchone()[0]
    assert n_fq == 0, "检验登记/未出结论不放行"

    # 质检通过 → 放行=独立事实
    conn.execute("UPDATE prod.quality_inspection SET conclusion='pass' WHERE id=%s", (insp,))
    conn.execute("INSERT INTO prod.final_qualification(actual_component_id, is_qualified, released_by, "
                 "released_at, occurred_at) VALUES (%s, true, %s, %s, %s)", (ac, inspector, NOW, NOW))
    n_fq = conn.execute("SELECT count(*) FROM prod.final_qualification WHERE actual_component_id=%s AND "
                        "is_qualified AND NOT revoked", (ac,)).fetchone()[0]
    assert n_fq == 1, "放行事实落库"

    # 当前放行唯一：第二笔未撤销的合格放行被拒
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.final_qualification(actual_component_id, is_qualified, released_by, released_at, "
          "occurred_at) VALUES (%s, true, %s, %s, %s)", (ac, inspector, NOW, NOW),
          frag="ix_final_qualification_current")


# ============ J-2 返工不重复增加需求 ============

def test_j2_rework_no_duplicate_requirement(conn):
    b = B(conn)
    pid, sid = b.project()
    team = b.team()
    cli = b.list_item(sid)
    ac = b.component(sid, cli, "J2")
    step = b.route_step(pid)

    t1 = b.task(ac, step, team)
    # 返工=新任务（attempt=2，血缘 rework_of；make_type 终局 T-6）
    t2 = b.task(ac, step, team, attempt=2, rework_of=t1)

    # 需求为批次快照（B 类）：返工任务创建不新增任何需求行
    m = b.material()
    req = conn.execute("INSERT INTO whs.material_requirement(subproject_id, calc_batch, created_at) "
                       "VALUES (%s, 'CB-J2', %s) RETURNING id", (sid, NOW)).fetchone()[0]
    conn.execute("INSERT INTO whs.material_requirement_item(requirement_id, material_id, req_quantity, "
                 "occurred_at) VALUES (%s, %s, 100, %s)", (req, m, NOW))

    n_req = conn.execute("SELECT count(*) FROM whs.material_requirement_item WHERE requirement_id=%s",
                         (req,)).fetchone()[0]
    assert n_req == 1, "返工后需求快照仍为 1 行（不重复增加）"

    # 同批次同材料重复需求行被结构拒绝
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO whs.material_requirement_item(requirement_id, material_id, req_quantity, occurred_at) "
          "VALUES (%s, %s, 50, %s)", (req, m, NOW), frag="uq_material_requirement_item_req_material")

    # 返工检验：attempt 递增（同构件同类型同 attempt 唯一），first attempt 已 fail 留档
    itype = conn.execute("SELECT id FROM ref.inspection_type ORDER BY id LIMIT 1").fetchone()[0]
    inspector = b.user()
    insp1 = conn.execute("INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, attempt, "
                         "conclusion, inspector_id, occurred_at) VALUES (%s, %s, 1, 'fail', %s, %s) RETURNING id",
                         (ac, itype, inspector, NOW)).fetchone()[0]
    conn.execute("INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, attempt, "
                 "conclusion, inspector_id, occurred_at) VALUES (%s, %s, 2, 'pass', %s, %s)",
                 (ac, itype, inspector, NOW))
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.quality_inspection(actual_component_id, inspection_type_id, attempt, conclusion, "
          "inspector_id, occurred_at) VALUES (%s, %s, 1, 'pass', %s, %s)", (ac, itype, inspector, NOW),
          frag="uq_quality_inspection_component_type_attempt")
    _ = (t2, insp1)
