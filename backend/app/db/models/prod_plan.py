"""prod schema — plan / task / report layer (11 of 34 tables).

Design doc: database_design_v1.2.md chapter 8 (8.1-8.4).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_task_status, enum_make_type

SCHEMA = "prod"


class ProductionPlan(TableBase, ALifecycleMixin):
    """8.1 计划头；(subproject_id, cycle_type, cycle_start) 唯一。"""
    __tablename__ = "production_plan"
    __table_args__ = (
        UniqueConstraint("subproject_id", "cycle_type", "cycle_start",
                         name="uq_production_plan_subproject_cycle"),
        CheckConstraint("cycle_type IN ('month','week','day')", name="ck_production_plan_cycle_type_values"),
        CheckConstraint("status IN ('draft','approved','frozen')", name="ck_production_plan_status_values"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    cycle_type: Mapped[str] = mapped_column(String(8), nullable=False)
    cycle_start: Mapped[date] = mapped_column(Date, nullable=False)
    time_range: Mapped[str | None] = mapped_column(String(64))
    compiled_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))


class ProductionPlanVersion(TableBase, BFactMixin):
    """8.1 计划版本（只追加；V1 下发后冻结 RED-12）。"""
    __tablename__ = "production_plan_version"
    __table_args__ = (
        UniqueConstraint("plan_id", "version_no", name="uq_production_plan_version_plan_version_no"),
        {"schema": SCHEMA},
    )
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_plan.id", ondelete="RESTRICT"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime)
    adjust_reason_category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"))
    adjust_reason: Mapped[str | None] = mapped_column(String(512))
    approved_ref_type: Mapped[str | None] = mapped_column(String(32), server_default=text("'approval_record'"))
    approved_ref_id: Mapped[int | None] = mapped_column(BigInteger)


class ProductionPlanLine(TableBase, ALifecycleMixin):
    """8.1 计划行（RED-10 粒度=构件+工序步骤实例；行上无数量列，汇总由行计数）。"""
    __tablename__ = "production_plan_line"
    __table_args__ = (
        UniqueConstraint("plan_version_id", "actual_component_id", "route_template_step_id",
                         name="uq_production_plan_line_triple"),
        Index("ix_production_plan_line_plan_version", "plan_version_id"),
        Index("ix_production_plan_line_actual_component", "actual_component_id"),
        {"schema": SCHEMA},
    )
    plan_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.production_plan_version.id", ondelete="RESTRICT"), nullable=False)
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    route_template_step_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eng.route_template_step.id", ondelete="RESTRICT"), nullable=False)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    target_completed_at: Mapped[date | None] = mapped_column(Date)


class PlanAdjustment(TableBase, BFactMixin):
    """8.1 计划调整事件（任何字段变更=新版本行+本事件）。"""
    __tablename__ = "plan_adjustment"
    __table_args__ = {"schema": SCHEMA}
    plan_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.production_plan_version.id", ondelete="RESTRICT"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(2000))
    new_value: Mapped[str | None] = mapped_column(String(2000))
    reason_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"), nullable=False)
    impact_desc: Mapped[str | None] = mapped_column(String(512))
    approval_ref_type: Mapped[str | None] = mapped_column(String(32), server_default=text("'approval_record'"))
    approval_ref_id: Mapped[int | None] = mapped_column(BigInteger)


class ProductionTask(TableBase, ALifecycleMixin):
    """8.2 生产任务：身份三元组 (actual_component_id, route_template_step_id, attempt)；
    make_type 任务级（MCR-3，T-6 终局）；约束 27 条件 CHECK；execute_team 单值（约束 4）。"""
    __tablename__ = "production_task"
    __table_args__ = (
        UniqueConstraint("actual_component_id", "route_template_step_id", "attempt",
                         name="uq_production_task_identity_triple"),
        CheckConstraint(
            "(make_type = 'outsource' AND supplier_id IS NOT NULL) OR (make_type = 'inhouse' AND supplier_id IS NULL)",
            name="ck_production_task_make_type_supplier"),
        Index("ix_production_task_actual_component", "actual_component_id"),
        Index("ix_production_task_team_status", "execute_team_id", "status"),
        Index("ix_production_task_plan_line", "plan_line_id"),
        Index("ix_production_task_step", "route_template_step_id"),
        Index("ix_production_task_rework_of", "rework_of_task_id"),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    route_template_step_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eng.route_template_step.id", ondelete="RESTRICT"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    execute_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    make_type: Mapped[str] = mapped_column(enum_make_type, nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.supplier.id", ondelete="RESTRICT"))
    plan_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.production_plan_line.id", ondelete="RESTRICT"))
    rework_of_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"))
    rework_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.rework_order.id", ondelete="RESTRICT"))
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(enum_task_status, nullable=False, server_default=text("'pending'"))


class TaskParticipant(TableBase, BFactMixin):
    """8.3 任务参与人（一任务多人）。"""
    __tablename__ = "task_participant"
    __table_args__ = (
        UniqueConstraint("task_id", "employee_id", name="uq_task_participant_task_employee"),
        {"schema": SCHEMA},
    )
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    contribution_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))


class TaskEvent(TableBase, BFactMixin):
    """8.3 任务事件流水（D 类；暂停/恢复/取消全写此表）。"""
    __tablename__ = "task_event"
    __table_args__ = (
        CheckConstraint("event_type IN ('start','pause','resume','complete','cancel')",
                        name="ck_task_event_event_type_values"),
        Index("ix_task_event_task_occurred", "task_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"))
    duration_min: Mapped[int | None] = mapped_column(Integer)


class TaskCancellation(TableBase, BFactMixin):
    """8.3 取消事实；(task_id) 唯一。"""
    __tablename__ = "task_cancellation"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_task_cancellation_task_id"),
        {"schema": SCHEMA},
    )
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"), nullable=False)
    reason_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"), nullable=False)
    approver: Mapped[int | None] = mapped_column(BigInteger)
    need_regen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    regen_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"))


class PrimaryTeamAssignment(TableBase, ALifecycleMixin):
    """8.3 构件主责当前指派（部分唯一 WHERE is_current）。"""
    __tablename__ = "primary_team_assignment"
    __table_args__ = (
        Index("ix_primary_team_assignment_current", "actual_component_id", unique=True,
              postgresql_where=text("is_current")),
        {"schema": SCHEMA},
    )
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(BigInteger)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class PrimaryTeamChangeHistory(TableBase, BFactMixin):
    """8.3 主责变更史（D 类；不影响已完成执行记录 N-15）。"""
    __tablename__ = "primary_team_change_history"
    __table_args__ = {"schema": SCHEMA}
    component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    from_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    to_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)


class ProductionReport(TableBase, BFactMixin):
    """8.4 报工事实（append-only；NB-3 三层幂等）：
    client_token 网络层部分唯一；(task_id, action_key) 业务动作唯一；report_seq 显示序号无唯一约束。"""
    __tablename__ = "production_report"
    __table_args__ = (
        UniqueConstraint("task_id", "action_key", name="uq_production_report_task_action_key"),
        Index("ix_production_report_client_token", "client_token", unique=True,
              postgresql_where=text("client_token IS NOT NULL")),
        Index("ix_production_report_task", "task_id"),
        Index("ix_production_report_team_occurred", "execute_team_id", "occurred_at"),
        Index("ix_production_report_component", "actual_component_id"),
        CheckConstraint("channel IN ('scan','manual')", name="ck_production_report_channel_values"),
        {"schema": SCHEMA},
    )
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"), nullable=False)
    actual_component_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"), nullable=False)
    route_template_step_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eng.route_template_step.id", ondelete="RESTRICT"), nullable=False)
    operation_snapshot: Mapped[str | None] = mapped_column(String(64))
    execute_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    action_key: Mapped[str | None] = mapped_column(String(64))
    report_seq: Mapped[int | None] = mapped_column(Integer)
    client_token: Mapped[str | None] = mapped_column(String(64))


class ProductionReportWorker(TableBase, BFactMixin):
    """8.4 报工工人行（一人一行，至少一人=服务层 CHECK count>=1）。"""
    __tablename__ = "production_report_worker"
    __table_args__ = (
        UniqueConstraint("report_id", "employee_id", name="uq_production_report_worker_report_employee"),
        {"schema": SCHEMA},
    )
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_report.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    work_hours: Mapped[float | None] = mapped_column(Numeric(6, 2))


class ProductionMeasure(TableBase, BFactMixin):
    """8.4 度量行（度量≠件数；完成数量=COUNT 事实行 RED-07）。"""
    __tablename__ = "production_measure"
    __table_args__ = (
        UniqueConstraint("report_id", "measure_type", name="uq_production_measure_report_type"),
        CheckConstraint("measure_type IN ('weight','cut_length','weld_length','mach_length','hours','hole_count')",
                        name="ck_production_measure_type_values"),
        {"schema": SCHEMA},
    )
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prod.production_report.id", ondelete="RESTRICT"), nullable=False)
    measure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(12, 3))
    unit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ref.unit_of_measure.id", ondelete="RESTRICT"), nullable=False)
