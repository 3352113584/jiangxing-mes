"""All PostgreSQL ENUM types for MES V1.2 (design 0.5).

Uses SQLAlchemy Postgresql ENUM which emits CREATE TYPE for initial migration.
- Each ENUM is named `enum_<entity>_<column>` per design 0.1.
- Values match design chapter 15 (state machines 10) + 0.5 (all closed short enums).
"""
from sqlalchemy.dialects.postgresql import ENUM

# === 0.5 节 ENUM 清单（封闭短枚举，全 DB 强制）===

enum_project = ENUM(
    "draft", "preparing", "production", "paused",
    "production_complete", "shipping", "completed", "closed",
    name="enum_project",
    create_type=True,
)

enum_ac_production = ENUM(
    "not_started", "in_production", "paused", "production_completed",
    "in_stock", "on_pallet", "in_container", "shipped", "site_received",
    "scrapped",
    name="enum_ac_production",
    create_type=True,
)

enum_ac_quality = ENUM(
    "pending_inspection", "first_pass", "failed", "reworking",
    "reinspection", "final_qualified",
    name="enum_ac_quality",
    create_type=True,
)

enum_task_status = ENUM(
    "pending", "in_progress", "paused", "completed", "cancelled",
    name="enum_task_status",
    create_type=True,
)

enum_inspection = ENUM(
    "registered", "inspecting", "concluded",
    name="enum_inspection",
    create_type=True,
)

enum_equipment = ENUM(
    "running", "stopped", "fault", "under_maintenance",
    name="enum_equipment",
    create_type=True,
)

enum_exception = ENUM(
    "open", "processing", "closed",
    name="enum_exception",
    create_type=True,
)

enum_pallet = ENUM(
    "empty", "in_use", "loaded", "in_container",
    name="enum_pallet",
    create_type=True,
)

enum_container = ENUM(
    "empty", "loading", "sealed", "shipped", "returned",
    name="enum_container",
    create_type=True,
)

enum_shipment = ENUM(
    "draft", "confirmed", "in_transit", "delivered", "returned",
    name="enum_shipment",
    create_type=True,
)

enum_reservation = ENUM(
    "reserved", "allocated", "consumed", "released", "cancelled",
    name="enum_reservation",
    create_type=True,
)

enum_import_batch = ENUM(
    "uploading", "validating", "previewed", "approved",
    "success", "partial_success", "failed", "voided",
    name="enum_import_batch",
    create_type=True,
)

enum_import_row_status = ENUM(
    "created", "updated", "kept", "failed",
    "conflict", "rejected", "invalidated",
    name="enum_import_row_status",
    create_type=True,
)

enum_import_kind = ENUM(
    "initial", "corrected_resubmit", "new_data_version", "duplicate_rejected",
    name="enum_import_kind",
    create_type=True,
)

enum_make_type = ENUM(
    "inhouse", "outsource",
    name="enum_make_type",
    create_type=True,
)

enum_line_status = ENUM(
    "active", "deprecated",
    name="enum_line_status",
    create_type=True,
)

enum_step_status = ENUM(
    "active", "deprecated",
    name="enum_step_status",
    create_type=True,
)

enum_part_status = ENUM(
    "planned", "material_assigned", "cut", "consumed_assembled",
    "scrapped", "substituted", "cancelled",
    name="enum_part_status",
    create_type=True,
)

enum_membership = ENUM(
    "primary", "secondary",
    name="enum_membership",
    create_type=True,
)

enum_stock_movement = ENUM(
    "stock_in", "issue", "return", "transfer",
    "count_gain", "count_loss", "surplus_in", "surplus_issue", "other",
    name="enum_stock_movement",
    create_type=True,
)

enum_surplus = ENUM(
    "in_pool", "issued", "consumed", "scrapped",
    name="enum_surplus",
    create_type=True,
)

enum_correction = ENUM(
    "draft", "submitted", "approving", "approved", "applied", "rejected",
    name="enum_correction",
    create_type=True,
)

ALL_ENUMS = [
    enum_project, enum_ac_production, enum_ac_quality, enum_task_status,
    enum_inspection, enum_equipment, enum_exception, enum_pallet,
    enum_container, enum_shipment, enum_reservation, enum_import_batch,
    enum_import_row_status, enum_import_kind, enum_make_type,
    enum_line_status, enum_step_status, enum_part_status, enum_membership,
    enum_stock_movement, enum_surplus, enum_correction,
]
