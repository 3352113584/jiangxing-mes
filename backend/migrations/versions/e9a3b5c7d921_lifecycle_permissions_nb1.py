"""Phase 3 NB-1：A/B/C/D 生命周期分类的权限回收（18 章权威清单落库）。

依据 docs/database_design_v1.2.md 18 章（NB-1 收口权威清单，131 表逐张归类）：
- 全库统一 DELETE 策略：严禁物理 DELETE——mes_app 不授予任何表的 DELETE 权限；
- A(57)/C(14)：正常可更新——授予 UPDATE；
- B(48)：append-only——仅 10 张窄路径白名单表授予 UPDATE
  （drawing_revision 仅 is_effective；final_qualification 仅 revoke 置值；
   quality_inspection/material_consumption/material_issue_line/material_issue_document/
   import_row/component_list_import_batch/import_correction_result/purchase_receipt_item
   由 T-8~T-14 触发器拦截白名单外变更）；
- D(12)：事件/审计/导入历史——严禁任何 UPDATE/DELETE。

权限矩阵（mes_app 应用角色）：
- SELECT + INSERT：全部 131 表
- UPDATE：81 表（A 57 + C 14 + B 白名单 10）
- DELETE / TRUNCATE / REFERENCES / TRIGGER：0 表
- 序列：USAGE, SELECT（IDENTITY BY DEFAULT 插入需 USAGE）

Revision ID: e9a3b5c7d921
Revises: d8f2a4c6e810
Create Date: 2026-09-18
"""
from alembic import op

revision = "e9a3b5c7d921"
down_revision = "d8f2a4c6e810"
branch_labels = None
depends_on = None

SCHEMAS = ["ref", "md", "eng", "imp", "prod", "whs", "ship", "aud"]

# A 类 57 表（18 章权威清单逐张核对）
A_CLASS = {
    "md": [
        "main_project", "subproject", "employee", "team", "user_account",
        "team_membership", "secondment_record", "team_leader_history",
        "role", "permission", "role_permission", "user_role",
        "data_scope_policy", "segregation_rule",
        "material", "supplier", "warehouse", "storage_location",
    ],
    "eng": [
        "engineering_object", "drawing", "engineering_binding",
        "component_bom_template", "bom_template_line",
        "route_template", "route_template_step",
    ],
    "prod": [
        "component_list_item", "actual_component", "part_instance",
        "qr_code_registry", "production_plan", "production_plan_line",
        "production_task", "primary_team_assignment", "nesting_batch",
        "ncr", "equipment",
    ],
    "whs": [
        "purchase_order", "purchase_order_item", "po_item_allocation",
        "material_certificate", "material_requirement",
        "surplus_material", "stock_balance", "inventory_check",
        "material_reservation", "finished_goods_stock",
    ],
    "ship": [
        "pallet", "pallet_load", "shipping_container", "container_load",
        "mixed_load_authorization", "shipment", "transport_status_ext",
    ],
    "aud": [
        "exception_event", "correction_request",
        "notification_delivery", "plan_progress_snapshot",
    ],
}

# C 类 14 表
C_CLASS = {
    "ref": [
        "operation_type", "inspection_type", "exception_category",
        "component_type_dict", "component_feature_dict", "subproject_type",
        "reason_dictionary", "unit_of_measure", "acceptance_result",
        "component_type_mapping", "qr_scan_access", "code_rule", "system_config",
    ],
    "imp": ["import_field_mapping"],
}

# B 类窄路径白名单 10 表（UPDATE 由触发器拦截白名单外变更）
B_WHITELIST = {
    "eng": ["drawing_revision"],
    "imp": ["component_list_import_batch", "import_row", "import_correction_result"],
    "prod": ["quality_inspection", "final_qualification"],
    "whs": [
        "purchase_receipt_item", "material_consumption",
        "material_issue_document", "material_issue_line",
    ],
}

_ROLE = "mes_app"

_CREATE_ROLE_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
        CREATE ROLE {_ROLE} LOGIN;
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO {_ROLE}', current_database());
END
$$;
"""

_GRANT_SQL = f"""
-- schema 使用权
GRANT USAGE ON SCHEMA {", ".join(SCHEMAS)} TO {_ROLE};

-- 全部表：SELECT + INSERT（当前 + 未来默认权限）
{chr(10).join(f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {s} TO {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT SELECT, INSERT ON TABLES TO {_ROLE};" for s in SCHEMAS)}

-- 序列（IDENTITY BY DEFAULT 插入需要 USAGE）
{chr(10).join(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT USAGE, SELECT ON SEQUENCES TO {_ROLE};" for s in SCHEMAS)}
"""

_UPDATE_GRANTS = []


def _build_update_grants() -> str:
    lines = []
    for mapping in (A_CLASS, C_CLASS, B_WHITELIST):
        for schema, tables in mapping.items():
            for t in tables:
                lines.append(f"GRANT UPDATE ON TABLE {schema}.{t} TO {_ROLE};")
    return "\n".join(lines)


_REVOKE_SQL = f"""
{chr(10).join(f"REVOKE ALL ON ALL TABLES IN SCHEMA {s} FROM {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {s} FROM {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} REVOKE ALL ON TABLES FROM {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} REVOKE ALL ON SEQUENCES FROM {_ROLE};" for s in SCHEMAS)}
{chr(10).join(f"REVOKE USAGE ON SCHEMA {s} FROM {_ROLE};" for s in SCHEMAS)}
"""


def upgrade() -> None:
    op.execute(_CREATE_ROLE_SQL)
    op.execute(_GRANT_SQL)
    op.execute(_build_update_grants())


def downgrade() -> None:
    op.execute(_REVOKE_SQL)
