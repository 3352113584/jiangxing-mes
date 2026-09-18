"""seed ref dictionaries (design chapter 2) + md.role initial roles

Revision ID: a7c1d2e4b601
Revises: 0b4e2935fee4
Create Date: 2026-09-18

Idempotent: INSERT ... ON CONFLICT DO NOTHING on declared unique keys.
component_type_mapping NOT seeded (OPEN-2 pending business confirmation).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7c1d2e4b601'
down_revision: Union[str, Sequence[str], None] = '0b4e2935fee4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 2.1 工序字典：设计示例 8 项 + 钢结构通用 8 项（C 类，业务可增改停用）
OPERATION_TYPES = [
    # code, name, is_critical, is_countable, sort_no
    ('cutting', '下料', True, True, 10),
    ('assembly', '组立', True, True, 20),
    ('welding', '焊接', True, True, 30),
    ('fire_correction', '火校', False, True, 40),
    ('grinding', '打磨', False, True, 50),
    ('derusting', '除锈', False, True, 60),
    ('painting', '喷涂', False, True, 70),
    ('final_inspection', '成品检', True, False, 80),
    ('drilling', '钻孔', False, True, 15),
    ('edge_milling', '铣边', False, True, 25),
    ('shot_blasting', '抛丸', False, True, 55),
    ('pre_assembly', '预拼装', False, True, 65),
    ('galvanizing', '镀锌', False, True, 75),
    ('packing', '包装', False, True, 85),
    ('loading', '装车发运', False, True, 90),
    ('outsource_handling', '外协处理', False, True, 95),
]

# 2.2 检验类型（attempt 语义由 quality_inspection 承载）
INSPECTION_TYPES = [
    ('dimension', '尺寸检', 10),
    ('first_article', '首件检', 20),
    ('final', '成品检', 30),
    ('flaw_detection', '探伤（预留）', 40),
]

# 2.3 异常原因七分类（固定 seed）
EXCEPTION_CATEGORIES = [
    ('material', '材料异常', 10),
    ('equipment', '设备异常', 20),
    ('technical_drawing', '技术图纸异常', 30),
    ('production_organization', '生产组织异常', 40),
    ('quality', '质量异常', 50),
    ('logistics', '物流异常', 60),
    ('other', '其他', 70),
]

# 2.11 到货验收结论受控值域（N-2 落点，固定 4 值）
ACCEPTANCE_RESULTS = [
    ('qualified', '合格', 10),
    ('pending', '待处理', 20),
    ('rejected', '拒收', 30),
    ('concession', '让步接收', 40),
]

# 2.7 子项目类型（N-9 初始清单）
SUBPROJECT_TYPES = [
    ('workshop', '厂房', 10),
    ('office', '办公楼', 20),
    ('equipment_area', '设备区', 30),
    ('zone', '分区', 40),
]

# 2.7 细化原因字典（parent_category 对应七类大分类）
REASONS = [
    # code, name, parent_category, sort_no
    ('material_shortage', '缺料', 'material', 10),
    ('material_quality', '材料质量不合格', 'material', 20),
    ('equipment_fault', '设备故障', 'equipment', 10),
    ('equipment_maintenance', '设备保养', 'equipment', 20),
    ('drawing_change', '图纸变更', 'technical_drawing', 10),
    ('drawing_error', '图纸错误', 'technical_drawing', 20),
    ('schedule_adjust', '计划调整', 'production_organization', 10),
    ('task_cancel', '任务取消', 'production_organization', 20),
    ('quality_rework', '返工', 'quality', 10),
    ('quality_scrap', '报废', 'quality', 20),
    ('logistics_delay', '物流延误', 'logistics', 10),
    ('paused_by_customer', '客户原因暂停', 'other', 10),
]

# 2.7 计量单位（code, name, kind, sort_no）
UNITS = [
    ('piece', '件', 'piece', 10),
    ('kg', '千克', 'weight', 20),
    ('t', '吨', 'weight', 30),
    ('mm', '毫米', 'length', 40),
    ('m', '米', 'length', 50),
    ('m2', '平方米', 'area', 60),
]

# 2.8 编号规则（rule_key, prefix, date_format, seq_padding, reset_policy）
CODE_RULES = [
    ('issue_no', 'L', 'yyyyMMdd', 4, 'daily'),
    ('reservation_no', 'RY', None, 6, 'never'),
    ('receipt_no', 'SH', 'yyyyMMdd', 4, 'daily'),
    ('shipment_no', 'FY', 'yyyyMMdd', 4, 'daily'),
    ('exception_no', 'EX', 'yyyyMMdd', 4, 'daily'),
    ('ncr_no', 'NCR', 'yyyyMMdd', 4, 'daily'),
    ('inventory_check_no', 'PD', 'yyyyMMdd', 4, 'daily'),
    ('correction_request_no', 'CR', 'yyyyMMdd', 4, 'daily'),
    ('approval_no', 'AP', 'yyyyMMdd', 4, 'daily'),
    ('rework_order_no', 'RG', 'yyyyMMdd', 4, 'daily'),
    ('mixed_load_auth_no', 'HZ', None, 6, 'never'),
    ('component_scrap_no', 'BF', 'yyyyMMdd', 4, 'daily'),
]

# 2.9 系统开关（N-16 缺料拦截 / N-18 预计完成 / N-12 计划审批角色 / 分段报工）
SYSTEM_CONFIGS = [
    ('material_shortage_intercept', 'true', 'bool', 'N-16 缺料拦截（true=硬拦截）'),
    ('eta_calc_enabled', 'true', 'bool', 'N-18 预计完成时间计算开关'),
    ('plan_approval_role', 'planner', 'str', 'N-12 计划审批角色 role_code'),
    ('segment_report_enabled', 'true', 'bool', '分段报工开关'),
]

# 2.4 构件标准类型（R2-05 开放字典初始值）
COMPONENT_TYPES = [
    ('beam', '梁', 'main', 10),
    ('column', '柱', 'main', 20),
    ('support', '支撑', 'secondary', 30),
    ('purlin', '檩条', 'secondary', 40),
    ('plate_part', '板件', 'bulk', 50),
    ('misc', '其他', 'other', 90),
]

# 2.5 构件特征标签（承接非类型值）
COMPONENT_FEATURES = [
    ('with_shear_key', '备带抗剪键', 10),
    ('direct_delivery', '直发件', 20),
    ('outsource', '外协', 30),
    ('with_sleeve', '套管', 40),
    ('tie_rod', '拉杆', 50),
    ('bracket', '支座', 60),
    ('secondary_member', '次构件', 70),
    ('high_frequency_weld', '高频焊', 80),
]

# md.role 初始角色（is_system=true；RBAC/扫码访问配置的基础数据）
ROLES = [
    ('admin', '系统管理员', 10),
    ('warehouse_keeper', '仓管员', 20),
    ('production_dispatcher', '生产调度', 30),
    ('worker', '作业工人', 40),
    ('quality_inspector', '质检员', 50),
    ('planner', '计划员', 60),
    ('sales', '销售', 70),
    ('finance', '财务', 80),
    ('viewer', '只读查看', 90),
]


def _insert(table: str, columns: str, rows_sql: str, conflict: str) -> None:
    op.execute(
        f'INSERT INTO ref.{table} ({columns}) VALUES {rows_sql} ON CONFLICT {conflict} DO NOTHING'
    )


def upgrade() -> None:
    """Seed ref dictionaries + initial roles. Idempotent (ON CONFLICT DO NOTHING)."""
    # operation_type（唯一键 code）
    _insert(
        'operation_type',
        'code, name, is_critical, is_countable, sort_no',
        ', '.join(
            f"('{c}', '{n}', {ic}, {ik}, {s})"
            for c, n, ic, ik, s in OPERATION_TYPES
        ),
        '(code)',
    )
    # inspection_type
    _insert(
        'inspection_type', 'code, name, sort_no',
        ', '.join(f"('{c}', '{n}', {s})" for c, n, s in INSPECTION_TYPES), '(code)')
    # exception_category（固定七类）
    _insert(
        'exception_category', 'code, name, sort_no',
        ', '.join(f"('{c}', '{n}', {s})" for c, n, s in EXCEPTION_CATEGORIES), '(code)')
    # acceptance_result（N-2 固定四值）
    _insert(
        'acceptance_result', 'code, name, sort_no',
        ', '.join(f"('{c}', '{n}', {s})" for c, n, s in ACCEPTANCE_RESULTS), '(code)')
    # subproject_type
    _insert(
        'subproject_type', 'code, name, sort_no',
        ', '.join(f"('{c}', '{n}', {s})" for c, n, s in SUBPROJECT_TYPES), '(code)')
    # component_type_dict
    _insert(
        'component_type_dict', 'code, name, category_group, sort_no',
        ', '.join(f"('{c}', '{n}', '{g}', {s})" for c, n, g, s in COMPONENT_TYPES), '(code)')
    # component_feature_dict
    _insert(
        'component_feature_dict', 'code, name, sort_no',
        ', '.join(f"('{c}', '{n}', {s})" for c, n, s in COMPONENT_FEATURES), '(code)')
    # reason_dictionary（唯一键 (parent_category, code)；显式 NOT EXISTS 守卫处理 NULL）
    op.execute(
        'INSERT INTO ref.reason_dictionary (code, name, parent_category, sort_no) '
        + ' UNION ALL '.join(
            f"SELECT '{c}', '{n}', '{p}', {s} WHERE NOT EXISTS "
            f"(SELECT 1 FROM ref.reason_dictionary WHERE parent_category IS NOT DISTINCT FROM '{p}' AND code='{c}')"
            for c, n, p, s in REASONS
        )
    )
    # unit_of_measure（先建基准单位，再回填换算）
    _insert(
        'unit_of_measure', 'code, name, kind, sort_no',
        ', '.join(f"('{c}', '{n}', '{k}', {s})" for c, n, k, s in UNITS), '(code)')
    op.execute("UPDATE ref.unit_of_measure SET conversion_base_id = (SELECT id FROM ref.unit_of_measure WHERE code='kg'), conversion_rate = 1000 WHERE code='t' AND conversion_base_id IS NULL")
    op.execute("UPDATE ref.unit_of_measure SET conversion_base_id = (SELECT id FROM ref.unit_of_measure WHERE code='mm'), conversion_rate = 1000 WHERE code='m' AND conversion_base_id IS NULL")
    # code_rule
    op.execute(
        'INSERT INTO ref.code_rule (rule_key, prefix, date_format, seq_padding, reset_policy) '
        + ' UNION ALL '.join(
            f"SELECT '{k}', '{p}', {('\'%s\'' % d) if d else 'NULL'}, {pad}, '{r}' WHERE NOT EXISTS (SELECT 1 FROM ref.code_rule WHERE rule_key='{k}')"
            for k, p, d, pad, r in CODE_RULES
        )
    )
    # system_config
    op.execute(
        'INSERT INTO ref.system_config (config_key, config_value, value_type, description) '
        + ' UNION ALL '.join(
            f"SELECT '{k}', '{v}', '{t}', '{d}' WHERE NOT EXISTS (SELECT 1 FROM ref.system_config WHERE config_key='{k}')"
            for k, v, t, d in SYSTEM_CONFIGS
        )
    )
    # md.role 初始角色
    op.execute(
        'INSERT INTO md.role (role_code, name, is_system) '
        + ' UNION ALL '.join(
            f"SELECT '{c}', '{n}', true WHERE NOT EXISTS (SELECT 1 FROM md.role WHERE role_code='{c}')"
            for c, n, s in ROLES
        )
    )


def downgrade() -> None:
    """Seed downgrade: delete seeded rows by key (structure untouched)."""
    codes = {
        'operation_type': tuple(c for c, *_ in OPERATION_TYPES),
        'inspection_type': tuple(c for c, *_ in INSPECTION_TYPES),
        'exception_category': tuple(c for c, *_ in EXCEPTION_CATEGORIES),
        'acceptance_result': tuple(c for c, *_ in ACCEPTANCE_RESULTS),
        'subproject_type': tuple(c for c, *_ in SUBPROJECT_TYPES),
        'component_type_dict': tuple(c for c, *_ in COMPONENT_TYPES),
        'component_feature_dict': tuple(c for c, *_ in COMPONENT_FEATURES),
    }
    for table, cs in codes.items():
        op.execute(
            f"DELETE FROM ref.{table} WHERE code IN ({', '.join(f"'{c}'" for c in cs)})"
        )
    op.execute(
        "DELETE FROM ref.reason_dictionary WHERE code IN "
        f"({', '.join(f"'{c}'" for c, *_ in REASONS)})"
    )
    op.execute(
        "DELETE FROM ref.unit_of_measure WHERE code IN "
        f"({', '.join(f"'{c}'" for c, *_ in UNITS)})"
    )
    op.execute(
        "DELETE FROM ref.code_rule WHERE rule_key IN "
        f"({', '.join(f"'{k}'" for k, *_ in CODE_RULES)})"
    )
    op.execute(
        "DELETE FROM ref.system_config WHERE config_key IN "
        f"({', '.join(f"'{k}'" for k, *_ in SYSTEM_CONFIGS)})"
    )
    op.execute(
        "DELETE FROM md.role WHERE role_code IN "
        f"({', '.join(f"'{c}'" for c, *_ in ROLES)}) AND is_system = true"
    )
