"""Phase 3 NB-4：触发器 T-1~T-12 全量实现 + 生命周期守卫 T-13/T-14。

依据 docs/database_design_v1.2.md 13.1 触发器设计清单（NB-4 收口）：
- T-1  ship.shipment_snapshot        快照冻结（BEFORE UPDATE/DELETE 一律拒绝）
- T-2  prod.actual_component         补件血缘指向态校验（scrapped）
- T-3  prod.part_instance            零件替代指向态校验（substituted + reason/replaced_at 必填）
- T-4  eng.bom_template_line         模板行禁改（被引用后语义列禁改；DELETE 一律阻止）
- T-5  eng.route_template_step       工序行禁改（被引用后语义列/行删除阻止）
- T-6  prod.production_task          make_type 终局（禁改）
- T-7  md.material                   material_code 禁改
- T-8  imp.import_row                处理事务外整行冻结（GUC mes.import_processing；物理删除一律阻止）
- T-9  prod.quality_inspection       conclusion 一次置值 + 白名单 {conclusion, inspection_status}
- T-10 whs.material_consumption      is_effective 仅冲正路径（GUC mes.reversal_context + 同事务 reversal_record）
- T-11 whs.material_issue_line       issued_qty 聚合白名单（GUC mes.issue_posting + stock_ledger 聚合容差 0.001）
- T-12 prod.component_list_item      voided 后禁改禁删；已实例化构件禁止 void（NB-8）
补充守卫（18 章生命周期规则的实现层落点，非新业务规则）：
- T-13 whs.material_issue_document   仅 status 位可 UPDATE（draft→confirmed→voided，void 单向）
- T-14 whs.purchase_receipt_item     窄路径白名单：验收三列一次置值，其余全列不可变
- T-15 eng.drawing_revision          窄路径白名单：仅 is_effective 切换
- T-16 prod.final_qualification      窄路径白名单：仅 revoke 标记一次性置值

实现说明：
- T-2 设计值域 {scrapped, cancelled}：enum_ac_production 实际无 cancelled（仅 enum_part_status 有），
  指向态交集实现为 production_status='scrapped'，与 15 章 actual_component 状态机一致。
- GUC 事务标记（set_config('mes.xxx','on',true)）为事务本地作用域，事务提交即失效，
  与"同事务落库标记"语义配套（T-8/T-10/T-11）。

Revision ID: d8f2a4c6e810
Revises: a7c1d2e4b601
Create Date: 2026-09-18
"""
from alembic import op

revision = "d8f2a4c6e810"
down_revision = "a7c1d2e4b601"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- ============================================================
-- T-1 ship.shipment_snapshot 快照冻结
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t1_snapshot_freeze() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'T-1: ship.shipment_snapshot 为发运冻结快照，禁止 %（id=%）', TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t1_snapshot_freeze
    BEFORE UPDATE OR DELETE ON ship.shipment_snapshot
    FOR EACH ROW EXECUTE FUNCTION mes_t1_snapshot_freeze();

-- ============================================================
-- T-2 prod.actual_component 补件血缘指向态校验
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t2_ac_replacement_target() RETURNS trigger AS $$
DECLARE
    v_status text;
BEGIN
    IF NEW.replacement_for IS NOT NULL THEN
        IF NEW.replacement_for = NEW.id THEN
            RAISE EXCEPTION 'T-2: replacement_for 不能指向自身（id=%）', NEW.id;
        END IF;
        SELECT ac.production_status INTO v_status
          FROM prod.actual_component ac WHERE ac.id = NEW.replacement_for;
        IF v_status IS NULL THEN
            RAISE EXCEPTION 'T-2: replacement_for=% 指向的构件不存在', NEW.replacement_for;
        END IF;
        IF v_status <> 'scrapped' THEN
            RAISE EXCEPTION 'T-2: 补件血缘非法：replacement_for=% 指向态必须为 scrapped（当前 %）',
                NEW.replacement_for, v_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t2_ac_replacement_target
    BEFORE INSERT OR UPDATE OF replacement_for ON prod.actual_component
    FOR EACH ROW EXECUTE FUNCTION mes_t2_ac_replacement_target();

-- ============================================================
-- T-3 prod.part_instance 零件替代指向态校验
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t3_part_replacement_target() RETURNS trigger AS $$
DECLARE
    v_status text;
BEGIN
    IF NEW.replacement_of IS NOT NULL THEN
        IF NEW.replacement_of = NEW.id THEN
            RAISE EXCEPTION 'T-3: replacement_of 不能指向自身（id=%）', NEW.id;
        END IF;
        SELECT pi.status INTO v_status
          FROM prod.part_instance pi WHERE pi.id = NEW.replacement_of;
        IF v_status IS NULL THEN
            RAISE EXCEPTION 'T-3: replacement_of=% 指向的零件实例不存在', NEW.replacement_of;
        END IF;
        IF v_status <> 'substituted' THEN
            RAISE EXCEPTION 'T-3: 替代血缘非法：replacement_of=% 指向态必须为 substituted（当前 %）',
                NEW.replacement_of, v_status;
        END IF;
        IF NEW.replacement_reason IS NULL OR NEW.replaced_at IS NULL THEN
            RAISE EXCEPTION 'T-3: 替代事实行必须填写 replacement_reason 与 replaced_at（id=%）', NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t3_part_replacement_target
    BEFORE INSERT OR UPDATE OF replacement_of ON prod.part_instance
    FOR EACH ROW EXECUTE FUNCTION mes_t3_part_replacement_target();

-- ============================================================
-- T-4 eng.bom_template_line 模板行禁改
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t4_bom_line_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'T-4: eng.bom_template_line 禁止 DELETE（id=%）；改版=新行新 line_no', OLD.id;
    END IF;
    IF OLD.part_no IS DISTINCT FROM NEW.part_no
       OR OLD.part_name IS DISTINCT FROM NEW.part_name
       OR OLD.material_desc IS DISTINCT FROM NEW.material_desc
       OR OLD.qty_per_component IS DISTINCT FROM NEW.qty_per_component THEN
        IF EXISTS (SELECT 1 FROM prod.part_instance pi WHERE pi.bom_template_line_id = OLD.id) THEN
            RAISE EXCEPTION 'T-4: bom_template_line id=% 已被零件实例引用，语义列禁改（MCR-1）', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t4_bom_line_immutable
    BEFORE UPDATE OR DELETE ON eng.bom_template_line
    FOR EACH ROW EXECUTE FUNCTION mes_t4_bom_line_immutable();

-- ============================================================
-- T-5 eng.route_template_step 工序行禁改
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t5_step_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM prod.production_plan_line pl WHERE pl.route_template_step_id = OLD.id)
           OR EXISTS (SELECT 1 FROM prod.production_task t WHERE t.route_template_step_id = OLD.id)
           OR EXISTS (SELECT 1 FROM prod.production_report r WHERE r.route_template_step_id = OLD.id) THEN
            RAISE EXCEPTION 'T-5: route_template_step id=% 已被计划/任务/报工引用，禁止 DELETE', OLD.id;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.operation_type_id IS DISTINCT FROM NEW.operation_type_id
       OR OLD.default_requirement IS DISTINCT FROM NEW.default_requirement THEN
        IF EXISTS (SELECT 1 FROM prod.production_plan_line pl WHERE pl.route_template_step_id = OLD.id)
           OR EXISTS (SELECT 1 FROM prod.production_task t WHERE t.route_template_step_id = OLD.id)
           OR EXISTS (SELECT 1 FROM prod.production_report r WHERE r.route_template_step_id = OLD.id) THEN
            RAISE EXCEPTION 'T-5: route_template_step id=% 已被引用，语义列禁改（MCR-1）', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t5_step_immutable
    BEFORE UPDATE OR DELETE ON eng.route_template_step
    FOR EACH ROW EXECUTE FUNCTION mes_t5_step_immutable();

-- ============================================================
-- T-6 prod.production_task make_type 终局
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t6_task_make_type_final() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'T-6: production_task.make_type 任务创建后终局不可改（id=%，返工=新任务）', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t6_task_make_type_final
    BEFORE UPDATE OF make_type ON prod.production_task
    FOR EACH ROW EXECUTE FUNCTION mes_t6_task_make_type_final();

-- ============================================================
-- T-7 md.material material_code 禁改
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t7_material_code_final() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'T-7: material.material_code 永不可改（id=%，更正=新码新行，旧码 is_active=false）', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t7_material_code_final
    BEFORE UPDATE OF material_code ON md.material
    FOR EACH ROW EXECUTE FUNCTION mes_t7_material_code_final();

-- ============================================================
-- T-8 imp.import_row 处理事务外整行冻结
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t8_import_row_freeze() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'T-8: imp.import_row 禁止物理删除（id=%，两批次原文留存，缺失行走 invalidated）', OLD.id;
    END IF;
    IF COALESCE(current_setting('mes.import_processing', true), '') <> 'on' THEN
        RAISE EXCEPTION 'T-8: import_row id=% 处理事务外整行冻结；仅导入/修正处理事务内 set_config(''mes.import_processing'',''on'',true) 后可变更', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t8_import_row_freeze
    BEFORE UPDATE OR DELETE ON imp.import_row
    FOR EACH ROW EXECUTE FUNCTION mes_t8_import_row_freeze();

-- ============================================================
-- T-9 prod.quality_inspection conclusion 一次置值 + 白名单
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t9_quality_conclusion_once() RETURNS trigger AS $$
BEGIN
    -- 白名单外列变更一律阻止（B 类窄路径：仅 inspection_status 流转 + conclusion 一次置值）
    IF OLD.actual_component_id IS DISTINCT FROM NEW.actual_component_id
       OR OLD.inspection_type_id IS DISTINCT FROM NEW.inspection_type_id
       OR OLD.attempt IS DISTINCT FROM NEW.attempt
       OR OLD.inspector_id IS DISTINCT FROM NEW.inspector_id
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-9: quality_inspection id=% 白名单外列变更被阻止（仅 inspection_status/conclusion 可变）', OLD.id;
    END IF;
    -- conclusion 一次置值：已定值后再改/清空一律阻止（历史结论永久保留，修正=attempt+1 新行）
    IF OLD.conclusion IS NOT NULL AND NEW.conclusion IS DISTINCT FROM OLD.conclusion THEN
        RAISE EXCEPTION 'T-9: quality_inspection id=% conclusion 已定值（%），禁止再改/清空', OLD.id, OLD.conclusion;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t9_quality_conclusion_once
    BEFORE UPDATE ON prod.quality_inspection
    FOR EACH ROW EXECUTE FUNCTION mes_t9_quality_conclusion_once();

-- ============================================================
-- T-10 whs.material_consumption is_effective 仅冲正路径
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t10_consumption_reversal_only() RETURNS trigger AS $$
BEGIN
    -- 白名单外列变更一律阻止（消耗事实列永久保留）
    IF OLD.part_instance_id IS DISTINCT FROM NEW.part_instance_id
       OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
       OR OLD.source_batch_id IS DISTINCT FROM NEW.source_batch_id
       OR OLD.source_surplus_id IS DISTINCT FROM NEW.source_surplus_id
       OR OLD.planned_source_type IS DISTINCT FROM NEW.planned_source_type
       OR OLD.planned_source_id IS DISTINCT FROM NEW.planned_source_id
       OR OLD.substitution_reason IS DISTINCT FROM NEW.substitution_reason
       OR OLD.weight IS DISTINCT FROM NEW.weight
       OR OLD.length IS DISTINCT FROM NEW.length
       OR OLD.sheets IS DISTINCT FROM NEW.sheets
       OR OLD.cutting_result_line_id IS DISTINCT FROM NEW.cutting_result_line_id
       OR OLD.client_token IS DISTINCT FROM NEW.client_token
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-10: material_consumption id=% 白名单外列变更被阻止（仅 is_effective 经冲正路径可变）', OLD.id;
    END IF;
    IF OLD.is_effective IS DISTINCT FROM NEW.is_effective THEN
        IF NEW.is_effective IS TRUE THEN
            RAISE EXCEPTION 'T-10: material_consumption id=% is_effective false→true 一律阻止（冲销结果不可回滚）', OLD.id;
        END IF;
        -- true→false 仅冲正事务：GUC 事务标记 + 同事务 reversal_record 落库
        IF COALESCE(current_setting('mes.reversal_context', true), '') <> 'on' THEN
            RAISE EXCEPTION 'T-10: material_consumption id=% 非冲正事务上下文，禁止 is_effective true→false（须 set_config(''mes.reversal_context'',''on'',true)）', OLD.id;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM aud.reversal_record rr
             WHERE rr.original_ref_type = 'material_consumption'
               AND rr.original_ref_id = OLD.id
        ) THEN
            RAISE EXCEPTION 'T-10: material_consumption id=% 冲正事务内未先落库 reversal_record（original_ref_type=''material_consumption''）', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t10_consumption_reversal_only
    BEFORE UPDATE ON whs.material_consumption
    FOR EACH ROW EXECUTE FUNCTION mes_t10_consumption_reversal_only();

-- ============================================================
-- T-11 whs.material_issue_line issued_qty 聚合白名单
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t11_issue_line_agg_whitelist() RETURNS trigger AS $$
DECLARE
    v_agg numeric;
BEGIN
    -- 白名单外列变更一律阻止（单据事实列 append-only）
    IF OLD.issue_document_id IS DISTINCT FROM NEW.issue_document_id
       OR OLD.line_no IS DISTINCT FROM NEW.line_no
       OR OLD.material_id IS DISTINCT FROM NEW.material_id
       OR OLD.material_batch_id IS DISTINCT FROM NEW.material_batch_id
       OR OLD.storage_location_id IS DISTINCT FROM NEW.storage_location_id
       OR OLD.requested_qty IS DISTINCT FROM NEW.requested_qty
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-11: material_issue_line id=% 白名单外列变更被阻止（仅 issued_qty 可经过账刷新）', OLD.id;
    END IF;
    IF OLD.issued_qty IS DISTINCT FROM NEW.issued_qty THEN
        IF COALESCE(current_setting('mes.issue_posting', true), '') <> 'on' THEN
            RAISE EXCEPTION 'T-11: material_issue_line id=% issued_qty 仅过账/对账事务可刷新（须 set_config(''mes.issue_posting'',''on'',true)）', OLD.id;
        END IF;
        SELECT COALESCE(SUM(sl.qty_weight), 0) INTO v_agg
          FROM whs.stock_ledger sl
         WHERE sl.issue_line_id = NEW.id
           AND sl.movement_type = 'issue';
        IF NEW.issued_qty IS NULL OR ABS(NEW.issued_qty - v_agg) > 0.001 THEN
            RAISE EXCEPTION 'T-11: material_issue_line id=% issued_qty(%) 与流水聚合(%) 偏离超容差 0.001', OLD.id, NEW.issued_qty, v_agg;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t11_issue_line_agg_whitelist
    BEFORE UPDATE ON whs.material_issue_line
    FOR EACH ROW EXECUTE FUNCTION mes_t11_issue_line_agg_whitelist();

-- ============================================================
-- T-12 prod.component_list_item voided 冻结（NB-8）
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t12_list_item_void_freeze() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.row_status = 'voided' THEN
            RAISE EXCEPTION 'T-12: component_list_item id=% 已 voided，禁止删除（原值留存）', OLD.id;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.row_status = 'voided' THEN
        RAISE EXCEPTION 'T-12: component_list_item id=% 已 voided，整行禁改（row_status 单向 active→voided）', OLD.id;
    END IF;
    IF NEW.row_status = 'voided' AND OLD.row_status = 'active' THEN
        IF EXISTS (SELECT 1 FROM prod.actual_component ac WHERE ac.component_list_item_id = OLD.id) THEN
            RAISE EXCEPTION 'T-12: component_list_item id=% 已实例化构件，禁止 void（导入修正应转 conflict 人工决策）', OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t12_list_item_void_freeze
    BEFORE UPDATE OR DELETE ON prod.component_list_item
    FOR EACH ROW EXECUTE FUNCTION mes_t12_list_item_void_freeze();

-- ============================================================
-- T-13 whs.material_issue_document 仅 status 位可变（18.6 B 类窄路径）
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t13_issue_doc_status_only() RETURNS trigger AS $$
BEGIN
    IF OLD.issue_no IS DISTINCT FROM NEW.issue_no
       OR OLD.issued_at IS DISTINCT FROM NEW.issued_at
       OR OLD.issued_by IS DISTINCT FROM NEW.issued_by
       OR OLD.issue_to_type IS DISTINCT FROM NEW.issue_to_type
       OR OLD.issue_to_id IS DISTINCT FROM NEW.issue_to_id
       OR OLD.subproject_id IS DISTINCT FROM NEW.subproject_id
       OR OLD.remark IS DISTINCT FROM NEW.remark
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-13: material_issue_document id=% 仅 status 列允许 UPDATE（单据事实 append-only）', OLD.id;
    END IF;
    IF OLD.status = 'voided' AND NEW.status IS DISTINCT FROM 'voided' THEN
        RAISE EXCEPTION 'T-13: material_issue_document id=% 已作废（voided 终态），status 不可变更', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t13_issue_doc_status_only
    BEFORE UPDATE ON whs.material_issue_document
    FOR EACH ROW EXECUTE FUNCTION mes_t13_issue_doc_status_only();

-- ============================================================
-- T-14 whs.purchase_receipt_item 窄路径白名单（18.6：验收三列一次置值，其余全列不可变）
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t14_receipt_acceptance_once() RETURNS trigger AS $$
BEGIN
    -- 白名单外列变更一律阻止（车次事实列 append-only）
    IF OLD.receipt_id IS DISTINCT FROM NEW.receipt_id
       OR OLD.line_no IS DISTINCT FROM NEW.line_no
       OR OLD.material_id IS DISTINCT FROM NEW.material_id
       OR OLD.declared_qty IS DISTINCT FROM NEW.declared_qty
       OR OLD.declared_weight IS DISTINCT FROM NEW.declared_weight
       OR OLD.received_qty IS DISTINCT FROM NEW.received_qty
       OR OLD.received_weight IS DISTINCT FROM NEW.received_weight
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-14: purchase_receipt_item id=% 白名单外列变更被阻止（仅验收三列可置值）', OLD.id;
    END IF;
    -- 验收三列一次置值
    IF OLD.acceptance_result_id IS NOT NULL
       AND NEW.acceptance_result_id IS DISTINCT FROM OLD.acceptance_result_id THEN
        RAISE EXCEPTION 'T-14: purchase_receipt_item id=% 验收结论一次置值，禁止变更', OLD.id;
    END IF;
    IF OLD.accepted_at IS NOT NULL
       AND NEW.accepted_at IS DISTINCT FROM OLD.accepted_at THEN
        RAISE EXCEPTION 'T-14: purchase_receipt_item id=% accepted_at 一次置值，禁止变更', OLD.id;
    END IF;
    IF OLD.accepted_by IS NOT NULL
       AND NEW.accepted_by IS DISTINCT FROM OLD.accepted_by THEN
        RAISE EXCEPTION 'T-14: purchase_receipt_item id=% accepted_by 一次置值，禁止变更', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t14_receipt_acceptance_once
    BEFORE UPDATE ON whs.purchase_receipt_item
    FOR EACH ROW EXECUTE FUNCTION mes_t14_receipt_acceptance_once();

-- ============================================================
-- T-15 eng.drawing_revision 窄路径白名单（18.3：仅 is_effective 切换留史）
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t15_drawing_revision_effective_only() RETURNS trigger AS $$
BEGIN
    IF OLD.drawing_id IS DISTINCT FROM NEW.drawing_id
       OR OLD.revision_no IS DISTINCT FROM NEW.revision_no
       OR OLD.released_at IS DISTINCT FROM NEW.released_at
       OR OLD.file_ref IS DISTINCT FROM NEW.file_ref
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-15: drawing_revision id=% 白名单外列变更被阻止（仅 is_effective 可切换）', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t15_drawing_revision_effective_only
    BEFORE UPDATE ON eng.drawing_revision
    FOR EACH ROW EXECUTE FUNCTION mes_t15_drawing_revision_effective_only();

-- ============================================================
-- T-16 prod.final_qualification 窄路径白名单（18.5：仅 revoke 标记一次性置值）
-- ============================================================
CREATE OR REPLACE FUNCTION mes_t16_final_qualification_revoke_only() RETURNS trigger AS $$
BEGIN
    IF OLD.actual_component_id IS DISTINCT FROM NEW.actual_component_id
       OR OLD.is_qualified IS DISTINCT FROM NEW.is_qualified
       OR OLD.released_by IS DISTINCT FROM NEW.released_by
       OR OLD.released_at IS DISTINCT FROM NEW.released_at
       OR OLD.occurred_at IS DISTINCT FROM NEW.occurred_at
       OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at
       OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'T-16: final_qualification id=% 白名单外列变更被阻止（仅 revoke 标记可置值）', OLD.id;
    END IF;
    IF OLD.revoked AND (NEW.revoked IS DISTINCT FROM OLD.revoked
                        OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
        RAISE EXCEPTION 'T-16: final_qualification id=% revoke 已置值，不可反复变更', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_t16_final_qualification_revoke_only
    BEFORE UPDATE ON prod.final_qualification
    FOR EACH ROW EXECUTE FUNCTION mes_t16_final_qualification_revoke_only();
"""

DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trg_t16_final_qualification_revoke_only ON prod.final_qualification;
DROP FUNCTION IF EXISTS mes_t16_final_qualification_revoke_only();

DROP TRIGGER IF EXISTS trg_t15_drawing_revision_effective_only ON eng.drawing_revision;
DROP FUNCTION IF EXISTS mes_t15_drawing_revision_effective_only();

DROP TRIGGER IF EXISTS trg_t14_receipt_acceptance_once ON whs.purchase_receipt_item;
DROP FUNCTION IF EXISTS mes_t14_receipt_acceptance_once();

DROP TRIGGER IF EXISTS trg_t13_issue_doc_status_only ON whs.material_issue_document;
DROP FUNCTION IF EXISTS mes_t13_issue_doc_status_only();

DROP TRIGGER IF EXISTS trg_t12_list_item_void_freeze ON prod.component_list_item;
DROP FUNCTION IF EXISTS mes_t12_list_item_void_freeze();

DROP TRIGGER IF EXISTS trg_t11_issue_line_agg_whitelist ON whs.material_issue_line;
DROP FUNCTION IF EXISTS mes_t11_issue_line_agg_whitelist();

DROP TRIGGER IF EXISTS trg_t10_consumption_reversal_only ON whs.material_consumption;
DROP FUNCTION IF EXISTS mes_t10_consumption_reversal_only();

DROP TRIGGER IF EXISTS trg_t9_quality_conclusion_once ON prod.quality_inspection;
DROP FUNCTION IF EXISTS mes_t9_quality_conclusion_once();

DROP TRIGGER IF EXISTS trg_t8_import_row_freeze ON imp.import_row;
DROP FUNCTION IF EXISTS mes_t8_import_row_freeze();

DROP TRIGGER IF EXISTS trg_t7_material_code_final ON md.material;
DROP FUNCTION IF EXISTS mes_t7_material_code_final();

DROP TRIGGER IF EXISTS trg_t6_task_make_type_final ON prod.production_task;
DROP FUNCTION IF EXISTS mes_t6_task_make_type_final();

DROP TRIGGER IF EXISTS trg_t5_step_immutable ON eng.route_template_step;
DROP FUNCTION IF EXISTS mes_t5_step_immutable();

DROP TRIGGER IF EXISTS trg_t4_bom_line_immutable ON eng.bom_template_line;
DROP FUNCTION IF EXISTS mes_t4_bom_line_immutable();

DROP TRIGGER IF EXISTS trg_t3_part_replacement_target ON prod.part_instance;
DROP FUNCTION IF EXISTS mes_t3_part_replacement_target();

DROP TRIGGER IF EXISTS trg_t2_ac_replacement_target ON prod.actual_component;
DROP FUNCTION IF EXISTS mes_t2_ac_replacement_target();

DROP TRIGGER IF EXISTS trg_t1_snapshot_freeze ON ship.shipment_snapshot;
DROP FUNCTION IF EXISTS mes_t1_snapshot_freeze();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
