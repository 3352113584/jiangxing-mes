"""prod schema — nesting/cutting + quality/equipment (15 of 34 tables).

Design doc: database_design_v1.2.md chapters 8.5, 9, 10.1.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_inspection, enum_equipment

SCHEMA = "prod"


# ============ 8.5 套料与切割 ============

class NestingBatch(TableBase, ALifecycleMixin):
    """8.5 套料批次（计划层，不碰库存账；N-5 双归属 scope 二选一非空）。"""
    __tablename__ = "nesting_batch"
    __table_args__ = (
        UniqueConstraint("nesting_batch_no", name="uq_nesting_batch_no"),
        CheckConstraint("scope IN ('main_project','subproject')", name="ck_nesting_batch_scope_values"),
        CheckConstraint(
            "(scope = 'main_project' AND main_project_id IS NOT NULL AND subproject_id IS NULL) OR "
            "(scope = 'subproject' AND subproject_id IS NOT NULL AND main_project_id IS NULL)",
            name="ck_nesting_batch_scope_match"),
        {"schema": SCHEMA},
    )
    import_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("imp.nesting_import_batch.id", ondelete="RESTRICT"))
    nesting_batch_no: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    main_project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"))
    subproject_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"))
    plate_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class NestingDetail(TableBase, BFactMixin):
    """8.5 套料计划明细（不是实际材料来源——实际走 material_consumption，R2-01）。"""
    __tablename__ = "nesting_detail"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_no", name="uq_nesting_detail_batch_line_no"),
        Index("ix_nesting_detail_part_instance", "part_instance_id"),
        {"schema": SCHEMA},
    )
    batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.nesting_batch.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("whs.material_batch.id", ondelete="RESTRICT"), nullable=False)
    part_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.part_instance.id", ondelete="RESTRICT"))
    planned_utilization: Mapped[float | None] = mapped_column(Numeric(5, 4))
    planned_pieces: Mapped[int | None] = mapped_column(Integer)


class CuttingRecord(TableBase, BFactMixin):
    """8.5 实际下料事实。"""
    __tablename__ = "cutting_record"
    __table_args__ = (
        UniqueConstraint("cut_no", name="uq_cutting_record_cut_no"),
        {"schema": SCHEMA},
    )
    nesting_batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.nesting_batch.id", ondelete="RESTRICT"))
    cut_no: Mapped[str] = mapped_column(String(32), nullable=False)
    cut_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"))
    equipment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prod.equipment.id", ondelete="RESTRICT"))


class CuttingResultLine(TableBase, BFactMixin):
    """8.5 切割结果行（append-only）。"""
    __tablename__ = "cutting_result_line"
    __table_args__ = (
        Index("ix_cutting_result_line_part_instance", "part_instance_id"),
        {"schema": SCHEMA},
    )
    cutting_record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.cutting_record.id", ondelete="RESTRICT"), nullable=False)
    part_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.part_instance.id", ondelete="RESTRICT"))
    consumed_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    surplus_created: Mapped[bool | None] = mapped_column(Boolean)
    scrap_weight: Mapped[float | None] = mapped_column(Numeric(12, 3))
    diff_remark: Mapped[str | None] = mapped_column(String(512))


class NestingDrawingFile(TableBase, BFactMixin):
    """8.5 套料图/程序登记。"""
    __tablename__ = "nesting_drawing_file"
    __table_args__ = (
        CheckConstraint("file_kind IN ('drawing','program')", name="ck_nesting_drawing_file_kind_values"),
        {"schema": SCHEMA},
    )
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prod.nesting_batch.id", ondelete="RESTRICT"))
    file_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)


# ============ 9. 质量 ============

class QualityInspection(TableBase, BFactMixin):
    """9.1 检验事实（B 类窄路径白名单 T-9）：唯一键含 attempt（约束 7）；
    conclusion 一次置值 NULL→值仅一次，历史结论永久保留（NB-2）。"""
    __tablename__ = "quality_inspection"
    __table_args__ = (
        UniqueConstraint("actual_component_id", "inspection_type_id", "attempt",
                         name="uq_quality_inspection_component_type_attempt"),
        CheckConstraint("conclusion IN ('pass','fail')", name="ck_quality_inspection_conclusion_values"),
        Index("ix_quality_inspection_component_attempt", "actual_component_id", "attempt"),
        Index("ix_quality_inspection_conclusion_occurred", "conclusion", "occurred_at"),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    inspection_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.inspection_type.id", ondelete="RESTRICT"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    inspection_status: Mapped[str] = mapped_column(enum_inspection, nullable=False, server_default=text("'registered'"))
    conclusion: Mapped[str | None] = mapped_column(String(8))
    inspector_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)


class QualityDefect(TableBase, BFactMixin):
    """9.2 缺陷行（一检验多缺陷；不用数量×构件表达）。"""
    __tablename__ = "quality_defect"
    __table_args__ = {"schema": SCHEMA}
    inspection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.quality_inspection.id", ondelete="RESTRICT"), nullable=False)
    defect_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"))
    location_desc: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))


class Ncr(TableBase, ALifecycleMixin):
    """9.2 不合格品报告（一单多缺陷/多构件——构件经 defect→inspection 上溯）。"""
    __tablename__ = "ncr"
    __table_args__ = (
        UniqueConstraint("ncr_no", name="uq_ncr_no"),
        CheckConstraint("status IN ('open','dispositioning','closed')", name="ck_ncr_status_values"),
        {"schema": SCHEMA},
    )
    ncr_no: Mapped[str] = mapped_column(String(32), nullable=False)
    inspection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.quality_inspection.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    disposition_summary: Mapped[str | None] = mapped_column(String(1000))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReworkOrder(TableBase, BFactMixin):
    """9.2 返工指令（触发新 attempt 任务，不改原检验/任务）。"""
    __tablename__ = "rework_order"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_rework_order_no"),
        CheckConstraint("source_type IN ('inspection','ncr','engineering_change')",
                        name="ck_rework_order_source_type_values"),
        Index("ix_rework_order_source", "source_ref_type", "source_ref_id"),
        {"schema": SCHEMA},
    )
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rework_scope: Mapped[str | None] = mapped_column(String(255))
    reason_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"), nullable=False)
    approved_ref_type: Mapped[str | None] = mapped_column(String(32), server_default=text("'approval_record'"))
    approved_ref_id: Mapped[int | None] = mapped_column(BigInteger)


class FinalQualification(TableBase, BFactMixin):
    """9.2 最终合格放行事实（驾驶舱口径事实源；当前放行部分唯一；撤销一次性置值）。"""
    __tablename__ = "final_qualification"
    __table_args__ = (
        Index("ix_final_qualification_current", "actual_component_id", unique=True,
              postgresql_where=text("is_qualified AND NOT revoked")),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    is_qualified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    released_by: Mapped[int | None] = mapped_column(BigInteger)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoke_ref: Mapped[str | None] = mapped_column(String(255))


# ============ 10.1 设备（schema 归 prod——第 1/18 章分布，rel 55 笔记见实施文档）============

class Equipment(TableBase, ALifecycleMixin):
    """10.1 设备台账（A 类当前态）。"""
    __tablename__ = "equipment"
    __table_args__ = (
        UniqueConstraint("equipment_code", name="uq_equipment_code"),
        {"schema": SCHEMA},
    )
    equipment_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(enum_equipment, nullable=False, server_default=text("'running'"))


class EquipmentEvent(TableBase, BFactMixin):
    """10.1 设备事件（每段起止留痕，D 类）。"""
    __tablename__ = "equipment_event"
    __table_args__ = (
        CheckConstraint("event_type IN ('start','stop','fault','maintain','recover')",
                        name="ck_equipment_event_event_type_values"),
        Index("ix_equipment_event_equipment_occurred", "equipment_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    equipment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.equipment.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(512))
    reporter: Mapped[int | None] = mapped_column(BigInteger)


class EquipmentImpact(TableBase, BFactMixin):
    """10.1 设备影响关系（构件/班组/计划经任务上溯）。"""
    __tablename__ = "equipment_impact"
    __table_args__ = (
        UniqueConstraint("event_id", "task_id", name="uq_equipment_impact_event_task"),
        Index("ix_equipment_impact_task", "task_id"),
        {"schema": SCHEMA},
    )
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.equipment_event.id", ondelete="RESTRICT"), nullable=False)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"), nullable=False)
    impact_note: Mapped[str | None] = mapped_column(String(512))
