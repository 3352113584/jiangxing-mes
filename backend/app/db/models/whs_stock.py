"""whs schema — stock / issue / reservation / consumption / surplus (11 of 23 tables).

Design doc: database_design_v1.2.md chapters 7.4-7.11, 18.6.
NB-7: stock_balance (storage_location_id, material_batch_id) index.
NB-2: material_consumption.is_effective / material_issue_line.issued_qty narrow paths.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_reservation, enum_stock_movement, enum_surplus

SCHEMA = "whs"


class StockBalance(TableBase, ALifecycleMixin):
    """7.4 库存余额（可重建当前值；事实源=stock_ledger）。
    NB-7：(storage_location_id, material_batch_id) 复合索引支撑库位→现存查询路径。"""
    __tablename__ = "stock_balance"
    __table_args__ = (
        UniqueConstraint("material_batch_id", "storage_location_id",
                         name="uq_stock_balance_batch_location"),
        Index("ix_stock_balance_location_batch", "storage_location_id", "material_batch_id"),
        CheckConstraint("weight_kg >= 0", name="ck_stock_balance_weight_non_negative"),
        {"schema": SCHEMA},
    )
    material_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    storage_location_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"), nullable=False)
    length_total: Mapped[float | None] = mapped_column(Numeric(12, 3))
    pieces: Mapped[int | None] = mapped_column(Integer)
    sheets: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, server_default=text("0"))


class StockLedger(TableBase, BFactMixin):
    """7.5 库存流水（八类动作一本账，append-only；冲正=correction_of_id 反向行）。
    禁止用负数领料行冒充退料——退料是独立 movement_type='return'。"""
    __tablename__ = "stock_ledger"
    __table_args__ = (
        CheckConstraint("qty_weight <> 0", name="ck_stock_ledger_qty_weight_nonzero"),
        CheckConstraint(
            "movement_type NOT IN ('surplus_in','surplus_issue') OR surplus_id IS NOT NULL",
            name="ck_stock_ledger_surplus_required"),
        Index("ix_stock_ledger_batch_occurred", "material_batch_id", "occurred_at"),
        Index("ix_stock_ledger_surplus", "surplus_id"),
        Index("ix_stock_ledger_issue_line", "issue_line_id"),
        Index("ix_stock_ledger_occurred_at", "occurred_at"),
        Index("ix_stock_ledger_movement_occurred", "movement_type", "occurred_at"),
        {"schema": SCHEMA},
    )
    movement_type: Mapped[str] = mapped_column(enum_stock_movement, nullable=False)
    material_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    surplus_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.surplus_material.id", ondelete="RESTRICT"))
    storage_location_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"), nullable=False)
    qty_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    qty_pieces: Mapped[int | None] = mapped_column(Integer)
    issue_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_issue_line.id", ondelete="RESTRICT"))
    reservation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_reservation.id", ondelete="RESTRICT"))
    consumption_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_consumption.id", ondelete="RESTRICT"))
    return_reason_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"))
    correction_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.stock_ledger.id", ondelete="RESTRICT"))


class MaterialIssueDocument(TableBase, BFactMixin):
    """7.6 领料单头（G-1）：单据≠库存流水；作废走 status 位（void 单向）。
    18.6：仅 status 列允许 UPDATE（T-13 生命周期守卫触发器强制），其余列 append-only。"""
    __tablename__ = "material_issue_document"
    __table_args__ = (
        UniqueConstraint("issue_no", name="uq_material_issue_document_issue_no"),
        CheckConstraint("issue_to_type IN ('team','employee')",
                        name="ck_material_issue_document_issue_to_type_values"),
        CheckConstraint("status IN ('draft','confirmed','voided')",
                        name="ck_material_issue_document_status_values"),
        Index("ix_material_issue_document_issued_at", "issued_at"),
        Index("ix_material_issue_document_subproject", "subproject_id"),
        {"schema": SCHEMA},
    )
    issue_no: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issued_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)
    issue_to_type: Mapped[str] = mapped_column(String(16), nullable=False)
    issue_to_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subproject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"))
    remark: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))


class MaterialIssueLine(TableBase, BFactMixin):
    """7.7 领料明细行（G-1）：material_batch_id Mandatory（关系 94）；
    issued_qty=聚合重建缓存列（NB-2/T-11 白名单仅此一列）；一行可对应 0..N 条流水。"""
    __tablename__ = "material_issue_line"
    __table_args__ = (
        UniqueConstraint("issue_document_id", "line_no",
                         name="uq_material_issue_line_doc_line_no"),
        Index("ix_material_issue_line_document", "issue_document_id"),
        {"schema": SCHEMA},
    )
    issue_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_issue_document.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    material_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    storage_location_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"))
    requested_qty: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    issued_qty: Mapped[float | None] = mapped_column(Numeric(12, 3))


class MaterialReservation(TableBase, ALifecycleMixin):
    """7.8 库存预留（MCR-5/R34）：意向层，任何状态不产生 stock_ledger 行、不改 stock_balance（约束 31）。"""
    __tablename__ = "material_reservation"
    __table_args__ = (
        UniqueConstraint("reservation_no", name="uq_material_reservation_reservation_no"),
        CheckConstraint("reserved_weight > 0", name="ck_material_reservation_weight_positive"),
        Index("ix_material_reservation_batch_status", "material_batch_id", "status"),
        Index("ix_material_reservation_requirement_item", "requirement_item_id"),
        Index("ix_material_reservation_material_status", "material_id", "status"),
        {"schema": SCHEMA},
    )
    reservation_no: Mapped[str] = mapped_column(String(32), nullable=False)
    material_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.material.id", ondelete="RESTRICT"), nullable=False)
    material_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"))
    storage_location_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"))
    reserved_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    requirement_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_requirement_item.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(
        enum_reservation, nullable=False, server_default=text("'reserved'"))
    consumed_by_ledger_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.stock_ledger.id", ondelete="RESTRICT", use_alter=True))


class MaterialConsumption(TableBase, BFactMixin):
    """7.9 实际消耗事实（唯一实际消耗，R2-01 双层；NB-2 收口）：
    source_kind 判别+双列条件非空；part_instance_id 有效消耗部分唯一（防一料多记）；
    is_effective 仅冲正事务（同事务 reversal_record 落库+GUC 标记）经 T-10 置 false。"""
    __tablename__ = "material_consumption"
    __table_args__ = (
        CheckConstraint("source_kind IN ('raw_batch','surplus')",
                        name="ck_material_consumption_source_kind_values"),
        CheckConstraint(
            "(source_kind = 'raw_batch' AND source_batch_id IS NOT NULL) OR "
            "(source_kind = 'surplus' AND source_surplus_id IS NOT NULL)",
            name="ck_material_consumption_source_required"),
        CheckConstraint("planned_source_type IS NULL OR planned_source_type IN ('nesting_detail','material_batch')",
                        name="ck_material_consumption_planned_source_type_values"),
        Index("uq_material_consumption_part_effective", "part_instance_id", unique=True,
              postgresql_where=text("is_effective")),
        Index("ix_material_consumption_client_token", "client_token", unique=True,
              postgresql_where=text("client_token IS NOT NULL")),
        Index("ix_material_consumption_source_batch", "source_batch_id"),
        Index("ix_material_consumption_source_surplus", "source_surplus_id"),
        Index("ix_material_consumption_part", "part_instance_id"),
        Index("ix_material_consumption_occurred_at", "occurred_at"),
        {"schema": SCHEMA},
    )
    part_instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.part_instance.id", ondelete="RESTRICT"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"))
    source_surplus_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.surplus_material.id", ondelete="RESTRICT"))
    planned_source_type: Mapped[str | None] = mapped_column(String(16))
    planned_source_id: Mapped[int | None] = mapped_column(BigInteger)
    substitution_reason: Mapped[str | None] = mapped_column(String(255))
    weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    length: Mapped[float | None] = mapped_column(Numeric(12, 3))
    sheets: Mapped[float | None] = mapped_column(Numeric(12, 3))
    cutting_result_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.cutting_result_line.id", ondelete="RESTRICT"))
    is_effective: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"))
    client_token: Mapped[str | None] = mapped_column(String(64))


class SurplusMaterial(TableBase, ALifecycleMixin):
    """7.10 余料（MCR-2/R27）：source_batch_id 恒必填（Heat 不断链）；
    parent_surplus_id 自引用+CHECK id<>parent（循环禁止=应用层递归校验，I-5）。"""
    __tablename__ = "surplus_material"
    __table_args__ = (
        CheckConstraint("id <> parent_surplus_id", name="ck_surplus_material_no_self_parent"),
        CheckConstraint("weight > 0", name="ck_surplus_material_weight_positive"),
        Index("ix_surplus_material_source_batch", "source_batch_id"),
        Index("ix_surplus_material_parent", "parent_surplus_id"),
        Index("ix_surplus_material_status", "status"),
        {"schema": SCHEMA},
    )
    source_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    parent_surplus_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("whs.surplus_material.id", ondelete="RESTRICT"))
    source_cutting_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.cutting_result_line.id", ondelete="RESTRICT"))
    grade_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension_desc: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    in_public_pool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(enum_surplus, nullable=False, server_default=text("'in_pool'"))


class ScrapRecord(TableBase, BFactMixin):
    """7.11 废料事实（关系 34）：来源受控二值软引用（consumption/surplus）；append-only。"""
    __tablename__ = "scrap_record"
    __table_args__ = (
        CheckConstraint("source_type IN ('consumption','surplus')",
                        name="ck_scrap_record_source_type_values"),
        Index("ix_scrap_record_source", "source_type", "source_id"),
        {"schema": SCHEMA},
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255))


class InventoryCheck(TableBase, ALifecycleMixin):
    """7.11 盘点单；差异→stock_ledger 调整行（count_gain/count_loss）+aud 异常事件。"""
    __tablename__ = "inventory_check"
    __table_args__ = (
        UniqueConstraint("check_no", name="uq_inventory_check_check_no"),
        CheckConstraint("status IN ('open','submitted','closed')",
                        name="ck_inventory_check_status_values"),
        {"schema": SCHEMA},
    )
    check_no: Mapped[str] = mapped_column(String(32), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.warehouse.id", ondelete="RESTRICT"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))


class FinishedGoodsStock(TableBase, ALifecycleMixin):
    """7.11 成品一件一行（关系 70）：出库后行保留；在库部分唯一。"""
    __tablename__ = "finished_goods_stock"
    __table_args__ = (
        CheckConstraint("status IN ('in_stock','out')", name="ck_finished_goods_stock_status_values"),
        Index("uq_finished_goods_stock_in_stock", "actual_component_id", unique=True,
              postgresql_where=text("status = 'in_stock'")),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    storage_location_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"), nullable=False)
    stock_in_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'in_stock'"))


class FinishedGoodsEvent(TableBase, BFactMixin):
    """7.11 成品出入/移位事实（D 类，append-only）。"""
    __tablename__ = "finished_goods_event"
    __table_args__ = (
        CheckConstraint("event_type IN ('stock_in','stock_out','move')",
                        name="ck_finished_goods_event_event_type_values"),
        Index("ix_finished_goods_event_component", "component_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_location_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"))
    to_location_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.storage_location.id", ondelete="RESTRICT"))
