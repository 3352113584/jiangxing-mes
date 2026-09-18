"""whs schema — procurement / arrival / batch / weighing (12 of 23 tables).

Design doc: database_design_v1.2.md chapters 6, 7.1-7.3.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CHAR, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase

SCHEMA = "whs"


class PurchaseOrder(TableBase, ALifecycleMixin):
    """7.1 采购单头（N-4：main_project_id 可空=公司级集中采购）。"""
    __tablename__ = "purchase_order"
    __table_args__ = (
        UniqueConstraint("po_no", name="uq_purchase_order_po_no"),
        CheckConstraint("status IN ('draft','confirmed','closed')", name="ck_purchase_order_status_values"),
        {"schema": SCHEMA},
    )
    po_no: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.supplier.id", ondelete="RESTRICT"), nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date)
    main_project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))


class PurchaseOrderItem(TableBase, ALifecycleMixin):
    """7.1 采购行（供应商原始编码随单快照）。"""
    __tablename__ = "purchase_order_item"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_purchase_order_item_order_line_no"),
        Index("ix_purchase_order_item_order", "order_id"),
        {"schema": SCHEMA},
    )
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("whs.purchase_order.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    qty: Mapped[float | None] = mapped_column(Numeric(12, 3))
    weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 2))
    supplier_material_code_snapshot: Mapped[str | None] = mapped_column(String(64))


class PoItemAllocation(TableBase, ALifecycleMixin):
    """7.1 集中采购分摊（公司级未分摊=0 行，N-4）。"""
    __tablename__ = "po_item_allocation"
    __table_args__ = (
        UniqueConstraint("item_id", "subproject_id", name="uq_po_item_allocation_item_subproject"),
        {"schema": SCHEMA},
    )
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("whs.purchase_order_item.id", ondelete="RESTRICT"), nullable=False)
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    allocated_qty: Mapped[float | None] = mapped_column(Numeric(12, 3))


class PurchaseReceipt(TableBase, BFactMixin):
    """7.2 到货单头=到货车次（R61 冻结）：一 PO 多车次；登记不产生任何库存事实（约束 32）。"""
    __tablename__ = "purchase_receipt"
    __table_args__ = (
        UniqueConstraint("receipt_no", name="uq_purchase_receipt_receipt_no"),
        Index("ix_purchase_receipt_po", "purchase_order_id"),
        Index("ix_purchase_receipt_arrived_at", "arrived_at"),
        Index("ix_purchase_receipt_trip_no", "trip_no"),
        {"schema": SCHEMA},
    )
    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False)
    purchase_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.purchase_order.id", ondelete="RESTRICT"))
    trip_no: Mapped[str | None] = mapped_column(String(32))
    vehicle_plate: Mapped[str | None] = mapped_column(String(16))
    arrived_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)


class PurchaseReceiptItem(TableBase, BFactMixin):
    """7.3 到货明细=验收行：验收结论一次置值（N-2 受控值域 FK）；
    验收事务内按合格行生成 material_batch（默认唯一入口）。"""
    __tablename__ = "purchase_receipt_item"
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_no", name="uq_purchase_receipt_item_receipt_line_no"),
        Index("ix_purchase_receipt_item_receipt", "receipt_id"),
        {"schema": SCHEMA},
    )
    receipt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("whs.purchase_receipt.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    declared_qty: Mapped[float | None] = mapped_column(Numeric(12, 3))
    declared_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    received_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    received_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    acceptance_result_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.acceptance_result.id", ondelete="RESTRICT"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"))


class MaterialBatch(TableBase, BFactMixin):
    """6.1 材料批次（Heat 追溯锚点，NB-5 批次入口规则）：
    batch_source 三值 CHECK；默认唯一入口=验收事务；例外入口强制 source_ref+审批留痕。"""
    __tablename__ = "material_batch"
    __table_args__ = (
        UniqueConstraint("factory_batch_no", name="uq_material_batch_factory_batch_no"),
        UniqueConstraint("supplier_id", "heat_no", name="uq_material_batch_supplier_heat_no"),
        CheckConstraint("batch_source IN ('receipt_acceptance','opening','manual')",
                        name="ck_material_batch_batch_source_values"),
        CheckConstraint(
            "(batch_source = 'receipt_acceptance' AND receipt_item_id IS NOT NULL "
            " AND source_ref IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(batch_source IN ('opening','manual') AND receipt_item_id IS NULL "
            " AND source_ref IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_material_batch_entry_rules"),
        Index("ix_material_batch_heat_no", "heat_no"),
        Index("ix_material_batch_material", "material_id"),
        Index("ix_material_batch_source", "batch_source"),
        {"schema": SCHEMA},
    )
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    material_code_snapshot: Mapped[str | None] = mapped_column(String(32))
    factory_batch_no: Mapped[str] = mapped_column(String(64), nullable=False)
    heat_no: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.supplier.id", ondelete="RESTRICT"), nullable=False)
    grade_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    original_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    batch_source: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'receipt_acceptance'"))
    receipt_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.purchase_receipt_item.id", ondelete="RESTRICT"))
    received_at: Mapped[date | None] = mapped_column(Date)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)


class MaterialCertificate(TableBase, ALifecycleMixin):
    """6.2 质保书文件登记。"""
    __tablename__ = "material_certificate"
    __table_args__ = (
        UniqueConstraint("cert_no", name="uq_material_certificate_cert_no"),
        {"schema": SCHEMA},
    )
    cert_no: Mapped[str] = mapped_column(String(64), nullable=False)
    file_ref: Mapped[str | None] = mapped_column(String(512))
    issuer: Mapped[str | None] = mapped_column(String(128))
    issued_at: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(512))


class MaterialBatchCertificate(TableBase):
    """关系 18 junction：多批共用一质保书（复合主键）。"""
    __tablename__ = "material_batch_certificate"
    __table_args__ = {"schema": SCHEMA}
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), primary_key=True)
    cert_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_certificate.id", ondelete="RESTRICT"), primary_key=True)


class MaterialRequirement(TableBase, ALifecycleMixin):
    """6.3 需求单头；(subproject_id, calc_batch) 唯一。"""
    __tablename__ = "material_requirement"
    __table_args__ = (
        UniqueConstraint("subproject_id", "calc_batch", name="uq_material_requirement_subproject_calc_batch"),
        CheckConstraint("status IN ('open','closed')", name="ck_material_requirement_status_values"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    calc_batch: Mapped[str] = mapped_column(String(32), nullable=False)
    calc_at: Mapped[datetime | None] = mapped_column(DateTime)
    caliber_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'open'"))


class MaterialRequirementItem(TableBase, BFactMixin):
    """6.3 需求明细（每批次快照 B 类；req_quantity=七类数量之③物料侧）。"""
    __tablename__ = "material_requirement_item"
    __table_args__ = (
        UniqueConstraint("requirement_id", "material_id", name="uq_material_requirement_item_req_material"),
        {"schema": SCHEMA},
    )
    requirement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_requirement.id", ondelete="RESTRICT"), nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    req_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3))
    deduct_in_transit: Mapped[bool | None] = mapped_column(Boolean)
    deduct_surplus: Mapped[bool | None] = mapped_column(Boolean)


class WeighingRecord(TableBase, BFactMixin):
    """6.4 过磅事实（一到货可多次过磅；batch/receipt_item 二选一非空）。"""
    __tablename__ = "weighing_record"
    __table_args__ = (
        CheckConstraint("batch_id IS NOT NULL OR receipt_item_id IS NOT NULL",
                        name="ck_weighing_record_target_required"),
        CheckConstraint("weigh_kind IN ('supplier','inbound','factory')", name="ck_weighing_record_weigh_kind_values"),
        {"schema": SCHEMA},
    )
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"))
    receipt_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.purchase_receipt_item.id", ondelete="RESTRICT"))
    weigh_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    supplier_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    factory_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    weighed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    weigh_place: Mapped[str | None] = mapped_column(String(64))
    operator: Mapped[int | None] = mapped_column(BigInteger)


class WeightDiscrepancy(TableBase, BFactMixin):
    """6.5 磅差事实（只登记事实与决定，不做财务；settlement_basis 暂不冻结）。"""
    __tablename__ = "weight_discrepancy"
    __table_args__ = (
        CheckConstraint("batch_id IS NOT NULL OR receipt_item_id IS NOT NULL",
                        name="ck_weight_discrepancy_target_required"),
        {"schema": SCHEMA},
    )
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"))
    receipt_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.purchase_receipt_item.id", ondelete="RESTRICT"))
    discrepancy_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))
    handling_way: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    settlement_basis: Mapped[str | None] = mapped_column(String(64))
