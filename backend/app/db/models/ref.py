"""ref schema — Layer 1 dictionaries / controlled value domains (13 C-class tables).

Design doc: database_design_v1.2.md chapter 2. All tables C-class (config/dictionary).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AMasterDataMixin, Base, TableBase

SCHEMA = "ref"


class DictBase(TableBase, AMasterDataMixin):
    """Common shape for ref dictionaries (2 章): code/name/sort_no/description/is_active."""

    __abstract__ = True
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(String(255))


class OperationType(DictBase):
    __tablename__ = "operation_type"
    __table_args__ = {"schema": SCHEMA}
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_countable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class InspectionType(DictBase):
    __tablename__ = "inspection_type"
    __table_args__ = {"schema": SCHEMA}


class ExceptionCategory(DictBase):
    __tablename__ = "exception_category"
    __table_args__ = {"schema": SCHEMA}


class ComponentTypeDict(DictBase):
    __tablename__ = "component_type_dict"
    __table_args__ = (
        CheckConstraint("category_group IN ('main','secondary','bulk','other')", name="ck_component_type_dict_category_group_values"),
        {"schema": SCHEMA},
    )
    category_group: Mapped[str] = mapped_column(String(32), nullable=False)
    is_statistical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ComponentFeatureDict(DictBase):
    __tablename__ = "component_feature_dict"
    __table_args__ = {"schema": SCHEMA}


class ComponentTypeMapping(TableBase, AMasterDataMixin):
    """2.6 来源值映射（R2-05）。Unique (source_value, source_kind, source_label, mapping_version)."""
    __tablename__ = "component_type_mapping"
    __table_args__ = (
        UniqueConstraint("source_value", "source_kind", "source_label", "mapping_version", name="uq_component_type_mapping_source"),
        CheckConstraint("source_kind IN ('customer','file','manual')", name="ck_component_type_mapping_source_kind_values"),
        {"schema": SCHEMA},
    )
    source_value: Mapped[str] = mapped_column(String(128), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(128))
    target_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.component_type_dict.id", ondelete="RESTRICT")
    )
    target_feature_ids: Mapped[list | None] = mapped_column(ARRAY(BigInteger))
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account（无 FK，服务层校验，避免 schema 环）
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class SubprojectType(DictBase):
    __tablename__ = "subproject_type"
    __table_args__ = {"schema": SCHEMA}


class ReasonDictionary(TableBase, AMasterDataMixin):
    """2.7 细化原因字典；Unique (parent_category, code)."""
    __tablename__ = "reason_dictionary"
    __table_args__ = (
        UniqueConstraint("parent_category", "code", name="uq_reason_dictionary_parent_category_code"),
        {"schema": SCHEMA},
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(String(255))
    parent_category: Mapped[str | None] = mapped_column(String(32))


class UnitOfMeasure(DictBase):
    """2.7 计量单位；换算经基准单位 self FK."""
    __tablename__ = "unit_of_measure"
    __table_args__ = (
        CheckConstraint("kind IN ('piece','weight','length','area')", name="ck_unit_of_measure_kind_values"),
        {"schema": SCHEMA},
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    conversion_base_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.unit_of_measure.id", ondelete="RESTRICT")
    )
    conversion_rate: Mapped[float | None] = mapped_column(Numeric(12, 6))


class CodeRule(TableBase, AMasterDataMixin):
    """2.8 编号规则；seq_current 仅发号事务推进（18.1 C 类注记）。"""
    __tablename__ = "code_rule"
    __table_args__ = (
        CheckConstraint("reset_policy IN ('never','daily','monthly','yearly')", name="ck_code_rule_reset_policy_values"),
        {"schema": SCHEMA},
    )
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str | None] = mapped_column(String(16))
    suffix: Mapped[str | None] = mapped_column(String(16))
    date_format: Mapped[str | None] = mapped_column(String(32))
    seq_current: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    seq_padding: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("4"))
    reset_policy: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'never'"))


class SystemConfig(TableBase, AMasterDataMixin):
    """2.9 系统级业务开关."""
    __tablename__ = "system_config"
    __table_args__ = (
        CheckConstraint("value_type IN ('bool','int','str','json')", name="ck_system_config_value_type_values"),
        {"schema": SCHEMA},
    )
    config_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    config_value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))


class QrScanAccess(TableBase, AMasterDataMixin):
    """2.10 扫码访问控制策略；(role_id) 唯一。role_id → md.role（Optional FK）。"""
    __tablename__ = "qr_scan_access"
    __table_args__ = {"schema": SCHEMA}
    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.role.id", ondelete="RESTRICT"), unique=True
    )
    visible_scope: Mapped[dict | None] = mapped_column(JSONB)


class AcceptanceResult(DictBase):
    """2.11 到货验收结论受控值域（N-2 落点）。"""
    __tablename__ = "acceptance_result"
    __table_args__ = {"schema": SCHEMA}
