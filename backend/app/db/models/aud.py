"""aud schema — status history / exceptions / correction-reversal / approval / audit / notify (13 tables).

Design doc: database_design_v1.2.md chapters 3.3, 10.2-10.4, 18.8.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_correction, enum_exception, enum_project

SCHEMA = "aud"


class ProjectStatusHistory(TableBase, BFactMixin):
    """3.3 主/子项目状态迁移史（append-only；reason/reopened 语义由服务层强校验）。"""
    __tablename__ = "project_status_history"
    __table_args__ = (
        CheckConstraint("owner_type IN ('main_project','subproject')",
                        name="ck_project_status_history_owner_type_values"),
        Index("ix_project_status_history_owner", "owner_type", "owner_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_status: Mapped[str] = mapped_column(enum_project, nullable=False)
    to_status: Mapped[str] = mapped_column(enum_project, nullable=False)
    reason_category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.reason_dictionary.id", ondelete="RESTRICT"))
    reason_detail: Mapped[str | None] = mapped_column(String(512))
    reopened_reason: Mapped[str | None] = mapped_column(String(512))
    reopened_to_state: Mapped[str | None] = mapped_column(enum_project)
    operated_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ExceptionEvent(TableBase, ALifecycleMixin):
    """10.2 异常事件（一因多果不复制异常，ORANGE-06；other 类别 ⇒ other_reason 服务层必填）。"""
    __tablename__ = "exception_event"
    __table_args__ = (
        UniqueConstraint("exception_no", name="uq_exception_event_exception_no"),
        CheckConstraint("severity IN ('low','mid','high')",
                        name="ck_exception_event_severity_values"),
        CheckConstraint("found_way IN ('auto','manual')",
                        name="ck_exception_event_found_way_values"),
        Index("ix_exception_event_source", "source_ref_type", "source_ref_id"),
        {"schema": SCHEMA},
    )
    exception_no: Mapped[str] = mapped_column(String(32), nullable=False)
    exception_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.exception_category.id", ondelete="RESTRICT"), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    source_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    found_way: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(
        enum_exception, nullable=False, server_default=text("'open'"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_by: Mapped[int | None] = mapped_column(BigInteger)


class ExceptionImpact(TableBase, BFactMixin):
    """10.2 异常影响对象行（原因≠受影响班组，约束 20；≥1 行服务层保证）。"""
    __tablename__ = "exception_impact"
    __table_args__ = (
        Index("ix_exception_impact_exception", "exception_id"),
        {"schema": SCHEMA},
    )
    exception_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aud.exception_event.id", ondelete="RESTRICT"), nullable=False)
    component_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.actual_component.id", ondelete="RESTRICT"))
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.production_task.id", ondelete="RESTRICT"))
    plan_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("prod.production_plan_line.id", ondelete="RESTRICT"))
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"))


class ExceptionHandling(TableBase, BFactMixin):
    """10.2 异常处理记录（closed 前可多条）。"""
    __tablename__ = "exception_handling"
    __table_args__ = (
        Index("ix_exception_handling_exception", "exception_id"),
        {"schema": SCHEMA},
    )
    exception_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aud.exception_event.id", ondelete="RESTRICT"), nullable=False)
    handler_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str | None] = mapped_column(String(255))
    close_info: Mapped[str | None] = mapped_column(String(512))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class CorrectionRequest(TableBase, ALifecycleMixin):
    """10.3 更正申请（10.9 状态机；error_type 值域=N-23 配置化，DB 仅强制非空）。"""
    __tablename__ = "correction_request"
    __table_args__ = (
        UniqueConstraint("request_no", name="uq_correction_request_request_no"),
        CheckConstraint("error_type IS NOT NULL AND error_type <> ''",
                        name="ck_correction_request_error_type_present"),
        Index("ix_correction_request_source", "source_ref_type", "source_ref_id"),
        {"schema": SCHEMA},
    )
    request_no: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error_desc: Mapped[str | None] = mapped_column(String(512))
    reason: Mapped[str | None] = mapped_column(String(512))
    applicant: Mapped[int | None] = mapped_column(BigInteger)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        enum_correction, nullable=False, server_default=text("'draft'"))


class CorrectionApproval(TableBase, BFactMixin):
    """10.3 更正审批链（分级=配置 N-23）。"""
    __tablename__ = "correction_approval"
    __table_args__ = (
        UniqueConstraint("request_id", "approval_level",
                         name="uq_correction_approval_request_level"),
        CheckConstraint("conclusion IN ('approve','reject')",
                        name="ck_correction_approval_conclusion_values"),
        {"schema": SCHEMA},
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aud.correction_request.id", ondelete="RESTRICT"), nullable=False)
    approval_level: Mapped[int] = mapped_column(Integer, nullable=False)
    approver: Mapped[int | None] = mapped_column(BigInteger)
    conclusion: Mapped[str] = mapped_column(String(8), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    remark: Mapped[str | None] = mapped_column(String(512))


class CorrectionEntry(TableBase, BFactMixin):
    """10.3 更正结果（corrected_value JSONB 更正后值）。"""
    __tablename__ = "correction_entry"
    __table_args__ = (
        Index("ix_correction_entry_request", "request_id"),
        Index("ix_correction_entry_target", "target_ref_type", "target_ref_id"),
        {"schema": SCHEMA},
    )
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aud.correction_request.id", ondelete="RESTRICT"), nullable=False)
    target_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    corrected_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime)
    operator: Mapped[int | None] = mapped_column(BigInteger)


class ReversalRecord(TableBase, BFactMixin):
    """10.3 冲正记录（被下游引用时 approved ⇒ 必生成；T-10 依赖同事务落库标记）。"""
    __tablename__ = "reversal_record"
    __table_args__ = (
        Index("ix_reversal_record_request", "request_id"),
        Index("ix_reversal_record_original", "original_ref_type", "original_ref_id"),
        {"schema": SCHEMA},
    )
    request_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aud.correction_request.id", ondelete="RESTRICT"))
    original_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reversal_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aud.correction_entry.id", ondelete="RESTRICT"))
    redo_ref_type: Mapped[str | None] = mapped_column(String(32))
    redo_ref_id: Mapped[int | None] = mapped_column(BigInteger)


class ApprovalRecord(TableBase, BFactMixin):
    """10.3 通用审批事实（不复制各业务审批状态；target 受控清单服务层保证）。"""
    __tablename__ = "approval_record"
    __table_args__ = (
        UniqueConstraint("approval_no", name="uq_approval_record_approval_no"),
        CheckConstraint("conclusion IN ('approve','reject')",
                        name="ck_approval_record_conclusion_values"),
        Index("ix_approval_record_target", "target_ref_type", "target_ref_id"),
        {"schema": SCHEMA},
    )
    approval_no: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conclusion: Mapped[str] = mapped_column(String(8), nullable=False)
    approver: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    remark: Mapped[str | None] = mapped_column(String(512))


class OperationLog(TableBase, BFactMixin):
    """10.3 技术审计日志（append-only；扫码日志并入此表）。"""
    __tablename__ = "operation_log"
    __table_args__ = (
        Index("ix_operation_log_target", "target_ref_type", "target_ref_id"),
        Index("ix_operation_log_op_at", "op_at"),
        {"schema": SCHEMA},
    )
    operator_id: Mapped[int | None] = mapped_column(BigInteger)
    op_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref_type: Mapped[str | None] = mapped_column(String(32))
    target_ref_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    op_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NotificationMessage(TableBase):
    """10.4 通知消息（D 类，append-only）。"""
    __tablename__ = "notification_message"
    __table_args__ = (
        Index("ix_notification_message_receiver", "receiver_user_id"),
        Index("ix_notification_message_source", "source_ref_type", "source_ref_id"),
        {"schema": SCHEMA},
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    source_ref_type: Mapped[str | None] = mapped_column(String(32))
    source_ref_id: Mapped[int | None] = mapped_column(BigInteger)
    receiver_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)


class NotificationDelivery(TableBase, ALifecycleMixin):
    """10.4 通知送达/阅读状态（仅收件人推进）。"""
    __tablename__ = "notification_delivery"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_notification_delivery_message_user"),
        CheckConstraint("status IN ('unread','read','processed')",
                        name="ck_notification_delivery_status_values"),
        {"schema": SCHEMA},
    )
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aud.notification_message.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'unread'"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlanProgressSnapshot(TableBase, ALifecycleMixin):
    """10.4 七指标进度快照（计算结果缓存可全量重建，不是事实源）。"""
    __tablename__ = "plan_progress_snapshot"
    __table_args__ = (
        Index("ix_plan_progress_snapshot_subproject", "subproject_id", "snapshot_at"),
        {"schema": SCHEMA},
    )
    subproject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    seven_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
