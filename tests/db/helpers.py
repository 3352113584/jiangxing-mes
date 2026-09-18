"""测试领域数据构造器（仅测试基础设施，不属于业务代码）。

说明：
- consumption 事实不产生独立 stock_ledger 行——其实际出库即领料/余料出库行（设计 7.5/7.9，
  防止领料与消耗双重扣账，H 组守恒测试覆盖）；
- 冲正反向行：movement_type 同原行、qty_weight 反号、correction_of_id 指向原行
  （qty CHECK <>0 允许；"禁止负数领料行冒充退料"指业务退料，冲正行以 correction_of_id 标记）。
"""
from datetime import datetime

NOW = datetime(2026, 9, 18, 10, 0, 0)


class B:
    """领域数据构造器：所有方法直接在给定连接内执行（不自动 commit）。"""

    def __init__(self, conn):
        self.conn = conn
        self._n = 0

    def _id(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    def _seq(self):
        self._n += 1
        return self._n

    # ============ 基础主数据 ============
    def user(self, name=None):
        return self._id("INSERT INTO md.user_account(username, password_hash) "
                        "VALUES (%s, 'x') RETURNING id", (name or f"u{self._seq()}",))

    def team(self, code=None):
        c = code or f"T{self._seq()}"
        return self._id("INSERT INTO md.team(team_code, name, team_type) "
                        "VALUES (%s, %s, 'production') RETURNING id", (c, c))

    def project(self):
        pid = self._id("INSERT INTO md.main_project(project_code, name) "
                       "VALUES (%s, '测试项目') RETURNING id", (f"P{self._seq()}",))
        sid = self._id("INSERT INTO md.subproject(main_project_id, subproject_code, name) "
                       "VALUES (%s, %s, '测试子项目') RETURNING id", (pid, f"S{self._seq()}"))
        return pid, sid

    def op_type(self):
        return self._id("SELECT id FROM ref.operation_type ORDER BY sort_no, id LIMIT 1")

    def material(self, code=None):
        unit = self._id("SELECT id FROM ref.unit_of_measure ORDER BY id LIMIT 1")
        return self._id("INSERT INTO md.material(material_code, name, category, grade, specification, unit_id) "
                        "VALUES (%s, '测试材料', 'plate', 'Q355B', 't10', %s) RETURNING id",
                        (code or f"M{self._seq()}", unit))

    def supplier(self, code=None):
        c = code or f"SUP{self._seq()}"
        return self._id("INSERT INTO md.supplier(supplier_code, name) VALUES (%s, %s) RETURNING id", (c, c))

    def wh_loc(self):
        wid = self._id("INSERT INTO md.warehouse(wh_code, name, wh_type) "
                       "VALUES (%s, '仓库', 'raw') RETURNING id", (f"W{self._seq()}",))
        lid = self._id("INSERT INTO md.storage_location(warehouse_id, loc_code) "
                       "VALUES (%s, %s) RETURNING id", (wid, f"L{self._seq()}"))
        return wid, lid

    def batch(self, material_id, supplier_id, heat, loc_id=None, weight=100.0,
              source="receipt_acceptance", approver=None):
        """创建批次；receipt_acceptance 走默认入口（先建车次+明细），opening/manual 走例外入口。"""
        if source == "receipt_acceptance":
            rid = self._id("INSERT INTO whs.purchase_receipt(receipt_no, trip_no, arrived_at, received_by, occurred_at) "
                           "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                           (f"RC{self._seq()}", f"TRIP{self._seq()}", NOW, self.user(), NOW))
            iid = self._id("INSERT INTO whs.purchase_receipt_item(receipt_id, line_no, material_id, "
                           "received_qty, received_weight, occurred_at) "
                           "VALUES (%s, 1, %s, 1, %s, %s) RETURNING id", (rid, material_id, weight, NOW))
            bid = self._id(
                "INSERT INTO whs.material_batch(material_id, factory_batch_no, heat_no, supplier_id, "
                "grade_snapshot, spec_snapshot, original_weight, batch_source, receipt_item_id, occurred_at) "
                "VALUES (%s, %s, %s, %s, 'Q355B', 't10', %s, 'receipt_acceptance', %s, %s) RETURNING id",
                (material_id, f"FB{self._seq()}", heat, supplier_id, weight, iid, NOW))
        else:
            assert approver is not None, "opening/manual 例外入口必须传 approver"
            bid = self._id(
                "INSERT INTO whs.material_batch(material_id, factory_batch_no, heat_no, supplier_id, "
                "grade_snapshot, spec_snapshot, original_weight, batch_source, source_ref, "
                "approved_by, approved_at, occurred_at) "
                "VALUES (%s, %s, %s, %s, 'Q355B', 't10', %s, %s, '期初导入', %s, %s, %s) RETURNING id",
                (material_id, f"FB{self._seq()}", heat, supplier_id, weight, source, approver, NOW, NOW))
        return bid

    def stock_in(self, batch_id, loc_id, weight, pieces=None):
        self.conn.execute(
            "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
            "qty_weight, qty_pieces, occurred_at) VALUES ('stock_in', %s, %s, %s, %s, %s)",
            (batch_id, loc_id, weight, pieces, NOW))
        self.conn.execute(
            "INSERT INTO whs.stock_balance(material_batch_id, storage_location_id, weight_kg, pieces) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (material_batch_id, storage_location_id) "
            "DO UPDATE SET weight_kg = stock_balance.weight_kg + EXCLUDED.weight_kg",
            (batch_id, loc_id, weight, pieces))

    def balance(self, batch_id, loc_id):
        row = self.conn.execute(
            "SELECT weight_kg FROM whs.stock_balance "
            "WHERE material_batch_id=%s AND storage_location_id=%s", (batch_id, loc_id)).fetchone()
        return float(row[0]) if row else 0.0

    # ============ 工程/构件/生产 ============
    def list_item(self, subproject_id, no=None, qty=1):
        return self._id("INSERT INTO prod.component_list_item(subproject_id, component_no, name, quantity) "
                        "VALUES (%s, %s, '测试构件', %s) RETURNING id",
                        (subproject_id, no or f"C{self._seq()}", qty))

    def bom_line(self, cli_id, line_no=1, part_no="P-01", qty=1):
        tid = self.conn.execute(
            "SELECT id FROM eng.component_bom_template WHERE component_list_item_id=%s AND is_effective",
            (cli_id,)).fetchone()
        if tid is None:
            tid = self._id("INSERT INTO eng.component_bom_template(component_list_item_id, template_no) "
                           "VALUES (%s, %s) RETURNING id", (cli_id, f"BT{self._seq()}"))
        else:
            tid = tid[0]
        return self._id("INSERT INTO eng.bom_template_line(template_id, line_no, part_no, qty_per_component) "
                        "VALUES (%s, %s, %s, %s) RETURNING id", (tid, line_no, part_no, qty))

    def qr(self, code=None):
        return self._id("INSERT INTO prod.qr_code_registry(qr_code) VALUES (%s) RETURNING id",
                        (code or f"QR{self._seq():08d}",))

    def component(self, subproject_id, cli_id, no, seq=1, qr_id=None):
        qid = qr_id or self.qr()
        acid = self._id("INSERT INTO prod.actual_component(subproject_id, component_list_item_id, "
                        "component_no, instance_sequence, qr_code_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (subproject_id, cli_id, no, seq, qid))
        self.conn.execute("UPDATE prod.qr_code_registry SET actual_component_id=%s WHERE id=%s", (acid, qid))
        return acid

    def part(self, ac_id, line_id, seq=1, part_no="P-01"):
        return self._id("INSERT INTO prod.part_instance(actual_component_id, bom_template_line_id, "
                        "instance_sequence, origin_part_no) VALUES (%s, %s, %s, %s) RETURNING id",
                        (ac_id, line_id, seq, part_no))

    def route_step(self, main_project_id, step_no=1):
        tid = self._id("INSERT INTO eng.route_template(main_project_id, name) "
                       "VALUES (%s, '路线') RETURNING id", (main_project_id,))
        return self._id("INSERT INTO eng.route_template_step(template_id, step_no, operation_type_id) "
                        "VALUES (%s, %s, %s) RETURNING id", (tid, step_no, self.op_type()))

    def task(self, ac_id, step_id, team_id, make_type="inhouse", attempt=1,
             rework_of=None, supplier_id=None):
        return self._id("INSERT INTO prod.production_task(actual_component_id, route_template_step_id, "
                        "attempt, execute_team_id, make_type, supplier_id, rework_of_task_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (ac_id, step_id, attempt, team_id, make_type, supplier_id, rework_of))

    def report(self, task_id, ac_id, step_id, team_id, action_key=None, client_token=None, seq=None):
        return self._id("INSERT INTO prod.production_report(task_id, actual_component_id, "
                        "route_template_step_id, execute_team_id, channel, action_key, report_seq, "
                        "client_token, occurred_at) VALUES (%s, %s, %s, %s, 'scan', %s, %s, %s, %s) RETURNING id",
                        (task_id, ac_id, step_id, team_id, action_key, seq, client_token, NOW))

    # ============ 仓库 ============
    def issue_doc(self, issued_by, team_id, subproject_id=None):
        return self._id("INSERT INTO whs.material_issue_document(issue_no, issued_at, issued_by, "
                        "issue_to_type, issue_to_id, subproject_id, occurred_at) "
                        "VALUES (%s, %s, %s, 'team', %s, %s, %s) RETURNING id",
                        (f"ILL{self._seq()}", NOW, issued_by, team_id, subproject_id, NOW))

    def issue_line(self, doc_id, line_no, material_id, batch_id, loc_id, requested):
        return self._id("INSERT INTO whs.material_issue_line(issue_document_id, line_no, material_id, "
                        "material_batch_id, storage_location_id, requested_qty, occurred_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (doc_id, line_no, material_id, batch_id, loc_id, requested, NOW))

    def post_issue(self, line_id, qty, batch_id, loc_id):
        """过账：GUC 事务标记 + ledger issue 行 + issued_qty 刷新 + 余额扣减（同一事务）。"""
        self.conn.execute("SELECT set_config('mes.issue_posting', 'on', true)")
        self.conn.execute(
            "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
            "qty_weight, issue_line_id, occurred_at) VALUES ('issue', %s, %s, %s, %s, %s)",
            (batch_id, loc_id, qty, line_id, NOW))
        self.conn.execute("UPDATE whs.material_issue_line SET issued_qty=%s WHERE id=%s", (qty, line_id))
        self.conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg - %s "
                          "WHERE material_batch_id=%s AND storage_location_id=%s", (qty, batch_id, loc_id))

    def consumption(self, part_id, batch_id, weight):
        """实际消耗事实（不产生独立 ledger 行——出库即领料行，防双重扣账）。"""
        return self._id("INSERT INTO whs.material_consumption(part_instance_id, source_kind, "
                        "source_batch_id, weight, occurred_at) "
                        "VALUES (%s, 'raw_batch', %s, %s, %s) RETURNING id",
                        (part_id, batch_id, weight, NOW))

    def surplus(self, batch_id, weight, parent_id=None):
        return self._id("INSERT INTO whs.surplus_material(source_batch_id, parent_surplus_id, "
                        "grade_snapshot, spec_snapshot, dimension_desc, weight, created_at) "
                        "VALUES (%s, %s, 'Q355B', 't10', '100x100', %s, %s) RETURNING id",
                        (batch_id, parent_id, weight, NOW))

    def surplus_in(self, surplus_id, batch_id, loc_id, weight):
        """余料入池 ledger 行（CHECK 强制 surplus_id 非空）。"""
        self.conn.execute(
            "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
            "qty_weight, surplus_id, occurred_at) VALUES ('surplus_in', %s, %s, %s, %s, %s)",
            (batch_id, loc_id, weight, surplus_id, NOW))
        self.conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg + %s "
                          "WHERE material_batch_id=%s AND storage_location_id=%s", (weight, batch_id, loc_id))

    def return_material(self, batch_id, loc_id, weight, reason_id=None):
        """退料：独立 movement_type='return'（禁止负数领料行冒充）。"""
        self.conn.execute(
            "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
            "qty_weight, return_reason_id, occurred_at) VALUES ('return', %s, %s, %s, %s, %s)",
            (batch_id, loc_id, weight, reason_id, NOW))
        self.conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg + %s "
                          "WHERE material_batch_id=%s AND storage_location_id=%s", (weight, batch_id, loc_id))

    def reversal(self, consumption_id, issue_row_id, batch_id, loc_id, weight):
        """冲正：reversal_record + 反向账行（correction_of_id，qty 反号=-weight）+ is_effective 翻转 + 余额回补。"""
        self.conn.execute("SELECT set_config('mes.reversal_context', 'on', true)")
        self.conn.execute(
            "INSERT INTO aud.reversal_record(original_ref_type, original_ref_id, occurred_at) "
            "VALUES ('material_consumption', %s, %s)", (consumption_id, NOW))
        self.conn.execute(
            "INSERT INTO whs.stock_ledger(movement_type, material_batch_id, storage_location_id, "
            "qty_weight, correction_of_id, occurred_at) VALUES ('issue', %s, %s, %s, %s, %s)",
            (batch_id, loc_id, -weight, issue_row_id, NOW))
        self.conn.execute("UPDATE whs.stock_balance SET weight_kg = weight_kg + %s "
                          "WHERE material_batch_id=%s AND storage_location_id=%s",
                          (weight, batch_id, loc_id))
        self.conn.execute("UPDATE whs.material_consumption SET is_effective=false WHERE id=%s",
                          (consumption_id,))
