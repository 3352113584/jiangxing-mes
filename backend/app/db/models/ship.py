"""ship schema — packaging / container / shipment / delivery (14 tables).

Design doc: database_design_v1.2.md chapter 11, 18.7.
NB-6: site_delivery_record.actual_component_id BIGINT NOT NULL FK → prod.actual_component.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_container, enum_pallet, enum_shipment

SCHEMA = "ship"


class Pallet(TableBase, ALifecycleMixin):
    """11.1 托盘资产（max_weight 为超重硬拦截依据，约束 10）。"""
    __tablename__ = "pallet"
    __table_args__ = (
        UniqueConstraint("pallet_no", name="uq_pallet_pallet_no"),
        CheckConstraint("max_weight > 0", name="ck_pallet_max_weight_positive"),
        {"schema": SCHEMA},
    )
    pallet_no: Mapped[str] = mapped_column(String(32), nullable=False)
    max_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    status: Mapped[str] = mapped_column(enum_pallet, nullable=False, server_default=text("'empty'"))
    current_main_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"))


class PalletLoad(TableBase, ALifecycleMixin):
    """11.2 当前装载：一件任意时刻仅一个有效托盘（约束 15）。"""
    __tablename__ = "pallet_load"
    __table_args__ = (
        Index("uq_pallet_load_current_component", "actual_component_id", unique=True,
              postgresql_where=text("is_current")),
        Index("uq_pallet_load_current", "pallet_id", "actual_component_id", unique=True,
              postgresql_where=text("is_current")),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    pallet_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"))


class PalletLoadHistory(TableBase, BFactMixin):
    """11.3 装载事件流水（append-only；repack 是事件非状态）。"""
    __tablename__ = "pallet_load_history"
    __table_args__ = (
        CheckConstraint("action IN ('load','remove','repack')",
                        name="ck_pallet_load_history_action_values"),
        Index("ix_pallet_load_history_pallet", "pallet_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    pallet_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"), nullable=False)
    component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    prev_pallet_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"))
    operator: Mapped[int | None] = mapped_column(BigInteger)
    weighed_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))


class PalletWeightRecord(TableBase, BFactMixin):
    """11.4 托盘称重事实（硬拦截比对源）。"""
    __tablename__ = "pallet_weight_record"
    __table_args__ = (
        Index("ix_pallet_weight_record_pallet", "pallet_id", "weighed_at"),
        {"schema": SCHEMA},
    )
    pallet_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"), nullable=False)
    gross_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    weighed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    weighed_by: Mapped[int | None] = mapped_column(BigInteger)


class ShippingContainer(TableBase, ALifecycleMixin):
    """11.4 集装箱资产（物理箱号会跨航次重复——部分唯一限定"当前在用"范围）。"""
    __tablename__ = "shipping_container"
    __table_args__ = (
        Index("uq_shipping_container_active_no", "container_no", unique=True,
              postgresql_where=text("status IN ('loading','sealed','shipped')")),
        CheckConstraint("max_weight > 0", name="ck_shipping_container_max_weight_positive"),
        {"schema": SCHEMA},
    )
    container_no: Mapped[str] = mapped_column(String(16), nullable=False)
    container_type: Mapped[str] = mapped_column(String(16), nullable=False)
    max_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(enum_container, nullable=False, server_default=text("'empty'"))


class ContainerLoad(TableBase, ALifecycleMixin):
    """11.5 当前装柜：一托盘当前仅一箱。"""
    __tablename__ = "container_load"
    __table_args__ = (
        Index("uq_container_load_current_pallet", "pallet_id", unique=True,
              postgresql_where=text("is_current")),
        Index("uq_container_load_current", "container_id", "pallet_id", unique=True,
              postgresql_where=text("is_current")),
        {"schema": SCHEMA},
    )
    container_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipping_container.id", ondelete="RESTRICT"), nullable=False)
    pallet_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"))


class ContainerLoadHistory(TableBase, BFactMixin):
    """11.5 装柜/卸柜/重装流水（append-only；mixed_load_auth_id 关联授权）。"""
    __tablename__ = "container_load_history"
    __table_args__ = (
        CheckConstraint("action IN ('load','unload','reload')",
                        name="ck_container_load_history_action_values"),
        Index("ix_container_load_history_container", "container_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    container_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipping_container.id", ondelete="RESTRICT"), nullable=False)
    pallet_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.pallet.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    operator: Mapped[int | None] = mapped_column(BigInteger)
    mixed_load_auth_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ship.mixed_load_authorization.id", ondelete="RESTRICT"))


class MixedLoadAuthorization(TableBase, ALifecycleMixin):
    """11.5 跨主项目混装授权（约束 9：装载前必须存在有效授权）。"""
    __tablename__ = "mixed_load_authorization"
    __table_args__ = (
        UniqueConstraint("auth_no", name="uq_mixed_load_authorization_auth_no"),
        {"schema": SCHEMA},
    )
    auth_no: Mapped[str] = mapped_column(String(32), nullable=False)
    main_project_a_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"), nullable=False)
    main_project_b_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"), nullable=False)
    authorized_by: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(512))
    scope_desc: Mapped[str | None] = mapped_column(String(512))
    approval_ref_type: Mapped[str | None] = mapped_column(
        String(32), server_default=text("'approval_record'"))
    approval_ref_id: Mapped[int | None] = mapped_column(BigInteger)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)


class ContainerWeightRecord(TableBase, BFactMixin):
    """11.5 集装箱称重（硬拦截源）。"""
    __tablename__ = "container_weight_record"
    __table_args__ = (
        Index("ix_container_weight_record_container", "container_id", "weighed_at"),
        {"schema": SCHEMA},
    )
    container_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipping_container.id", ondelete="RESTRICT"), nullable=False)
    gross_weight: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    weighed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    weighed_by: Mapped[int | None] = mapped_column(BigInteger)


class Shipment(TableBase, ALifecycleMixin):
    """11.6 发运单（draft 阶段可编辑；confirmed 后整行冻结，仅 status 状态机推进）。"""
    __tablename__ = "shipment"
    __table_args__ = (
        UniqueConstraint("shipment_no", name="uq_shipment_shipment_no"),
        {"schema": SCHEMA},
    )
    shipment_no: Mapped[str] = mapped_column(String(32), nullable=False)
    main_project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255))
    carrier: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(enum_shipment, nullable=False, server_default=text("'draft'"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)


class ShipmentSnapshot(TableBase):
    """11.7 不可变快照（confirmed 时刻逐构件一行，全部冗余冻结副本；T-1 永久冻结）。"""
    __tablename__ = "shipment_snapshot"
    __table_args__ = (
        UniqueConstraint("shipment_id", "actual_component_id",
                         name="uq_shipment_snapshot_shipment_component"),
        {"schema": SCHEMA},
    )
    shipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipment.id", ondelete="RESTRICT"), nullable=False)
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    component_no_snapshot: Mapped[str | None] = mapped_column(String(64))
    weight_snapshot: Mapped[float | None] = mapped_column(Numeric(12, 3))
    subproject_snapshot: Mapped[str | None] = mapped_column(String(64))
    pallet_no_snapshot: Mapped[str | None] = mapped_column(String(32))
    container_no_snapshot: Mapped[str | None] = mapped_column(String(16))
    qr_code_snapshot: Mapped[str | None] = mapped_column(String(64))
    snapshotted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipmentEvent(TableBase, BFactMixin):
    """11.6 发运状态事件（append-only；补发=新 shipment 行）。"""
    __tablename__ = "shipment_event"
    __table_args__ = (
        CheckConstraint("event_type IN ('confirm','depart','transit_node','arrive','sign','return','reship')",
                        name="ck_shipment_event_event_type_values"),
        Index("ix_shipment_event_shipment", "shipment_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    shipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipment.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict | None] = mapped_column(JSONB)
    operator: Mapped[int | None] = mapped_column(BigInteger)


class TransportStatusExt(TableBase, ALifecycleMixin):
    """11.6 V1 外部物流接口位（外部状态缓存列，可覆盖刷新）。"""
    __tablename__ = "transport_status_ext"
    __table_args__ = (
        UniqueConstraint("shipment_id", name="uq_transport_status_ext_shipment"),
        {"schema": SCHEMA},
    )
    shipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship.shipment.id", ondelete="RESTRICT"), nullable=False)
    vehicle_or_vessel: Mapped[str | None] = mapped_column(String(64))
    current_location: Mapped[str | None] = mapped_column(String(255))
    external_ref: Mapped[str | None] = mapped_column(String(128))


class SiteDeliveryRecord(TableBase, BFactMixin):
    """11.7 现场签收（V1 轻量；退运补发可多次；append-only）。
    NB-6：actual_component_id BIGINT NOT NULL FK → prod.actual_component（ON DELETE RESTRICT）。"""
    __tablename__ = "site_delivery_record"
    __table_args__ = (
        Index("ix_site_delivery_record_component_signed",
              "actual_component_id", "signed_at"),
        Index("ix_site_delivery_record_shipment", "shipment_id"),
        Index("ix_site_delivery_record_client_token", "client_token", unique=True,
              postgresql_where=text("client_token IS NOT NULL")),
        {"schema": SCHEMA},
    )
    shipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ship.shipment.id", ondelete="RESTRICT"))
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    signed_by_name: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    diff_remark: Mapped[str | None] = mapped_column(String(512))
    client_token: Mapped[str | None] = mapped_column(String(64))
