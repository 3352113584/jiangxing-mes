"""imp schema — Layer 4 import process domain (5 tables).

Design doc: database_design_v1.2.md chapter 5 (5.1-5.5).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_import_batch, enum_import_kind, enum_import_row_status

SCHEMA = "imp"


class ComponentListImportBatch(TableBase, BFactMixin):
    """5.1 构件清单导入批次（B 类，处理事务内 batch_status/统计列一次落定）。"""
    __tablename__ = "component_list_import_batch"
    __table_args__ = (
        UniqueConstraint("subproject_id", "file_hash", "mapping_version",
                         name="uq_component_list_import_batch_subproject_file_hash_mapping"),
        CheckConstraint("supersedes_batch_id IS NULL OR import_kind = 'corrected_resubmit'",
                        name="ck_component_list_import_batch_supersedes_requires_corrected"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sheet_detection: Mapped[dict | None] = mapped_column(JSONB)
    header_info: Mapped[dict | None] = mapped_column(JSONB)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_status: Mapped[str] = mapped_column(enum_import_batch, nullable=False, server_default=text("'uploading'"))
    success_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    import_kind: Mapped[str] = mapped_column(enum_import_kind, nullable=False, server_default=text("'initial'"))
    supersedes_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("imp.component_list_import_batch.id", ondelete="RESTRICT"))
    imported_by: Mapped[int] = mapped_column(BigInteger, nullable=False)  # → md.user_account
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ImportRow(TableBase, BFactMixin):
    """5.2 统一导入行（MCR-4/R41）；(import_batch_id, source_identity) 幂等唯一；
    source_row_number 仅定位不作身份（约束 29）；处理后整行冻结（T-8）；
    NB-8：result_status 含 invalidated（修正版缺失行的受控失效留证）。"""
    __tablename__ = "import_row"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "source_identity", name="uq_import_row_batch_source_identity"),
        CheckConstraint(
            "(target_ref_type IS NULL AND target_ref_id IS NULL) OR (target_ref_type IS NOT NULL AND target_ref_id IS NOT NULL)",
            name="ck_import_row_target_pair",
        ),
        CheckConstraint("target_ref_type IS NULL OR target_ref_type = 'component_list_item'",
                        name="ck_import_row_target_type_values"),
        Index("ix_import_row_batch_result", "import_batch_id", "result_status"),
        Index("ix_import_row_target", "target_ref_type", "target_ref_id"),
        Index("ix_import_row_corrected_from", "corrected_from_row_id"),
        {"schema": SCHEMA},
    )
    import_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("imp.component_list_import_batch.id", ondelete="RESTRICT"), nullable=False)
    source_sheet: Mapped[str | None] = mapped_column(String(64))
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_status: Mapped[str] = mapped_column(enum_import_row_status, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(4000))
    target_ref_type: Mapped[str | None] = mapped_column(String(32))
    target_ref_id: Mapped[int | None] = mapped_column(BigInteger)
    corrected_from_row_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("imp.import_row.id", ondelete="RESTRICT"))


class ImportCorrectionResult(TableBase, BFactMixin):
    """5.3 修正导入净效果（R2-04 + NB-8 rows_invalidated）。"""
    __tablename__ = "import_correction_result"
    __table_args__ = (
        UniqueConstraint("new_batch_id", name="uq_import_correction_result_new_batch_id"),
        {"schema": SCHEMA},
    )
    new_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("imp.component_list_import_batch.id", ondelete="RESTRICT"), nullable=False)
    superseded_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("imp.import_correction_result.id", ondelete="RESTRICT"))
    rows_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_kept: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_conflict: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_invalidated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImportFieldMapping(TableBase, ALifecycleMixin):
    """5.4 版本化字段映射（C 类；旧版本停用不删）。"""
    __tablename__ = "import_field_mapping"
    __table_args__ = (
        UniqueConstraint("version_no", "header_name", "column_index",
                         name="uq_import_field_mapping_version_header_column"),
        {"schema": SCHEMA},
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    header_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_field: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))


class NestingImportBatch(TableBase, BFactMixin):
    """5.5 套料导入批次（专业套料软件来源）。"""
    __tablename__ = "nesting_import_batch"
    __table_args__ = (
        UniqueConstraint("file_hash", name="uq_nesting_import_batch_file_hash"),
        {"schema": SCHEMA},
    )
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64))
    imported_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    check_result: Mapped[dict | None] = mapped_column(JSONB)
