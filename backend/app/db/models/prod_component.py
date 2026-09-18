"""prod schema — component identity layer (8 of 34 tables).

Design doc: database_design_v1.2.md chapter 5 (5.6-5.9) + chapter 1 table list.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Computed, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_ac_production, enum_ac_quality, enum_part_status

SCHEMA = "prod"


class ComponentListItem(TableBase, ALifecycleMixin):
    """5.6 构件清单行（A 类）；(subproject_id, component_no) 唯一；computed_weight 生成列；
    row_status active→voided 单向（NB-8/T-12）；voided 后语义列禁改。"""
    __tablename__ = "component_list_item"
    __table_args__ = (
        UniqueConstraint("subproject_id", "component_no", name="uq_component_list_item_subproject_component_no"),
        CheckConstraint("quantity > 0", name="ck_component_list_item_quantity_positive"),
        CheckConstraint("row_status IN ('active','voided')", name="ck_component_list_item_row_status_values"),
        Index("ix_component_list_item_subproject_component_no", "subproject_id", "component_no"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    component_no: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    drawing_no: Mapped[str | None] = mapped_column(String(64))
    drawing_revision_no: Mapped[str | None] = mapped_column(String(32))
    engineering_object_key: Mapped[str | None] = mapped_column(String(128))
    installation_location: Mapped[str | None] = mapped_column(String(255))
    material_desc: Mapped[str | None] = mapped_column(String(128))
    theoretical_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    computed_weight: Mapped[float | None] = mapped_column(
        Numeric(12, 3), Computed("theoretical_weight * quantity", persisted=True))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    source_remark: Mapped[str | None] = mapped_column(String(512))
    total_weight_declared: Mapped[float | None] = mapped_column(Numeric(12, 3))
    import_row_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("imp.import_row.id", ondelete="RESTRICT"))
    row_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))


class ComponentListItemFeature(TableBase):
    """R2-05 junction：清单行↔特征标签（复合主键）。"""
    __tablename__ = "component_list_item_feature"
    __table_args__ = (
        Index("ix_component_list_item_feature_feature_id", "feature_id"),
        {"schema": SCHEMA},
    )
    list_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.component_list_item.id", ondelete="RESTRICT"), primary_key=True)
    feature_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.component_feature_dict.id", ondelete="RESTRICT"), primary_key=True)


class ActualComponent(TableBase, ALifecycleMixin):
    """5.7 实际构件（核心聚合根）：一件一身份，无 quantity 列（约束 1）；
    三列业务唯一；QR 1:1 终身绑定；replacement_for 补件血缘（T-2 校验指向态）。"""
    __tablename__ = "actual_component"
    __table_args__ = (
        UniqueConstraint("subproject_id", "component_no", "instance_sequence",
                         name="uq_actual_component_identity_triple"),
        Index("ix_actual_component_qr_code_id", "qr_code_id", unique=True),
        Index("ix_actual_component_replacement_for_unique", "replacement_for", unique=True,
              postgresql_where=text("replacement_for IS NOT NULL")),
        Index("ix_actual_component_production_status", "production_status"),
        Index("ix_actual_component_quality_status", "quality_status"),
        Index("ix_actual_component_subproject_status", "subproject_id", "production_status"),
        Index("ix_actual_component_replacement_for", "replacement_for"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    component_list_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.component_list_item.id", ondelete="RESTRICT"), nullable=False)
    component_no: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    qr_code_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.qr_code_registry.id", ondelete="RESTRICT", use_alter=True), nullable=False)
    production_status: Mapped[str] = mapped_column(enum_ac_production, nullable=False, server_default=text("'not_started'"))
    quality_status: Mapped[str] = mapped_column(enum_ac_quality, nullable=False, server_default=text("'pending_inspection'"))
    actual_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    current_location_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"))
    current_pallet_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"))
    current_container_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ship.shipping_container.id", ondelete="RESTRICT"))
    replacement_for: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"))


class ActualComponentEvent(TableBase, BFactMixin):
    """5.9 构件履历事件流（D 类 append-only）。"""
    __tablename__ = "actual_component_event"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('start','pause','resume','complete','scrap','supplement','stock_in','move','ship','site_receive')",
            name="ck_actual_component_event_event_type_values"),
        Index("ix_actual_component_event_component_occurred", "actual_component_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)


class ComponentScrapRecord(TableBase, BFactMixin):
    """5.9 报废事实；一构件至多一次生效报废（partial unique WHERE is_effective）；scrap_no 序号不复用。"""
    __tablename__ = "component_scrap_record"
    __table_args__ = (
        UniqueConstraint("scrap_no", name="uq_component_scrap_record_scrap_no"),
        Index("ix_component_scrap_record_effective", "actual_component_id", unique=True,
              postgresql_where=text("is_effective")),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    scrap_no: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.exception_category.id", ondelete="RESTRICT"), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(String(512))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_effective: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class QrCodeRegistry(TableBase, ALifecycleMixin):
    """5.9 扫码域入口：qr_code 全局唯一；码-件 1:1（partial unique WHERE NOT NULL）；补打不换码。"""
    __tablename__ = "qr_code_registry"
    __table_args__ = (
        UniqueConstraint("qr_code", name="uq_qr_code_registry_qr_code"),
        Index("ix_qr_code_registry_actual_component_unique", "actual_component_id", unique=True,
              postgresql_where=text("actual_component_id IS NOT NULL")),
        {"schema": SCHEMA},
    )
    qr_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_component_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT", use_alter=True))
    printed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String(16), CheckConstraint("status IN ('active','voided')", name="ck_qr_code_registry_status_values"),
        nullable=False, server_default=text("'active'"))


class LabelPrintHistory(TableBase, BFactMixin):
    """5.9 补打记录（D 类）。"""
    __tablename__ = "label_print_history"
    __table_args__ = {"schema": SCHEMA}
    qr_code_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.qr_code_registry.id", ondelete="RESTRICT"), nullable=False)
    printed_by: Mapped[int | None] = mapped_column(BigInteger)
    printed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))


class PartInstance(TableBase, ALifecycleMixin):
    """5.8 零件实例（18.5 定 A 类）：身份三元组唯一；工程锚点锁定模板行（MCR-1）；
    replacement_of 零件替代血缘（T-3 校验 substituted + reason/replaced_at 必填）。"""
    __tablename__ = "part_instance"
    __table_args__ = (
        UniqueConstraint("actual_component_id", "bom_template_line_id", "instance_sequence",
                         name="uq_part_instance_identity_triple"),
        Index("ix_part_instance_replacement_of_unique", "replacement_of", unique=True,
              postgresql_where=text("replacement_of IS NOT NULL")),
        Index("ix_part_instance_actual_component", "actual_component_id"),
        Index("ix_part_instance_bom_line", "bom_template_line_id"),
        Index("ix_part_instance_replacement_of", "replacement_of"),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    bom_template_line_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eng.bom_template_line.id", ondelete="RESTRICT"), nullable=False)
    instance_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_part_no: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(enum_part_status, nullable=False, server_default=text("'planned'"))
    replacement_of: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.part_instance.id", ondelete="RESTRICT"))
    replacement_reason: Mapped[str | None] = mapped_column(String(255))
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime)
