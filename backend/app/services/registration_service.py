"""Phase 4 Sprint 1 — 构件生产工序登记服务（核心）。

严格遵循 Phase 4 应用层契约 V1.1：
- 幂等（§4）：client_token 网络层幂等 + (task_id, action_key) 业务动作幂等；命中即返回首次结果，绝不重复落库。
- 并发（§3/§4）：对 production_task 行 SELECT ... FOR UPDATE 串行化；同构件同工序仅首个成功，
  另一请求得到明确业务结果（ALREADY_COMPLETED），不产生重复生产事实。
- 状态机（§3.1/§3.2）：production_task.status 与 actual_component.production_status 仅按合法转换表推进；
  非法跳跃（如 completed 后再 start）被拒绝。历史事实（production_report）只追加，普通 UPDATE 不覆盖。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.eng import RouteTemplateStep
from app.db.models.md import Team
from app.db.models.prod_component import ActualComponent, ActualComponentEvent
from app.db.models.prod_plan import (
    ProductionReport,
    ProductionReportWorker,
    ProductionTask,
    TaskEvent,
)
from app.db.models.ref import OperationType
from app.services.component_service import resolve_component_by_qr
from app.services.errors import BusinessError


def _naive(dt: Optional[datetime]) -> datetime:
    return dt.replace(tzinfo=None) if dt and dt.tzinfo is not None else (dt or datetime.now())


def _op_name(db: Session, step_id: int) -> str:
    step = db.get(RouteTemplateStep, step_id)
    if step is None:
        return ""
    ot = db.get(OperationType, step.operation_type_id)
    return ot.name if ot else ""


def _result_from_report(db: Session, report: ProductionReport, *, idempotent: bool, status: str):
    task = db.get(ProductionTask, report.task_id)
    ac = db.get(ActualComponent, report.actual_component_id)
    team_name = db.execute(
        select(Team.name).where(Team.id == report.execute_team_id)
    ).scalar() or ""
    return {
        "report_id": report.id,
        "task_id": report.task_id,
        "actual_component_id": report.actual_component_id,
        "component_no": ac.component_no if ac else "",
        "instance_sequence": ac.instance_sequence if ac else 0,
        "operation_type_name": _op_name(db, report.route_template_step_id),
        "team_name": team_name,
        "status": status,
        "idempotent": idempotent,
        "message": "幂等返回首次登记结果" if idempotent else "登记成功",
    }


def register(
    db: Session,
    *,
    user_ctx,
    qr_code: Optional[str] = None,
    task_id: Optional[int] = None,
    client_token: str,
    action_key: Optional[str] = None,
    worker_ids: list[int],
    occurred_at: Optional[datetime] = None,
) -> dict:
    # 0. 当前用户必须有主属班组（Android/PC 登记主体）
    if not user_ctx.primary_team_id:
        raise BusinessError("NO_PRIMARY_TEAM", "当前账号无主属班组，无法登记", 403)

    # 1. 解析任务（扫码 OR 任务列表选择）
    if task_id is not None:
        task = db.get(ProductionTask, task_id)
        if task is None:
            raise BusinessError("TASK_NOT_FOUND", "任务不存在", 404)
    elif qr_code:
        ac = resolve_component_by_qr(db, qr_code)
        if ac is None:
            raise BusinessError("COMPONENT_NOT_FOUND", "构件二维码无效或未绑定构件", 404)
        task = db.execute(
            select(ProductionTask)
            .where(
                ProductionTask.actual_component_id == ac.id,
                ProductionTask.execute_team_id == user_ctx.primary_team_id,
                ProductionTask.status.in_(["pending", "in_progress"]),
            )
            .order_by(ProductionTask.attempt, ProductionTask.id)
        ).scalars().first()
        if task is None:
            # 场景 D：扫码构件不属于当前班组任务范围 → 拒绝
            raise BusinessError(
                "NOT_YOUR_TASK",
                "该构件不在当前班组的待执行任务范围内",
                403,
            )
    else:
        raise BusinessError("BAD_REQUEST", "必须提供 qr_code 或 task_id", 400)

    # 2. 权限硬校验（纵深防御）
    if task.execute_team_id != user_ctx.primary_team_id:
        raise BusinessError("NOT_YOUR_TASK", "无权登记该任务", 403)

    # 3. 幂等（网络层 client_token）
    existing = db.execute(
        select(ProductionReport).where(ProductionReport.client_token == client_token)
    ).scalars().first()
    if existing is not None:
        return _result_from_report(db, existing, idempotent=True, status="completed")

    # 4. 幂等（业务动作 (task_id, action_key)）
    ak = action_key or f"complete:{task.id}"
    existing = db.execute(
        select(ProductionReport).where(
            ProductionReport.task_id == task.id,
            ProductionReport.action_key == ak,
        )
    ).scalars().first()
    if existing is not None:
        return _result_from_report(db, existing, idempotent=True, status="completed")

    # 5. 并发 + 状态机：锁定任务行，串行化同构件同工序登记
    task = db.execute(
        select(ProductionTask).where(ProductionTask.id == task.id).with_for_update()
    ).scalar_one()

    if task.status == "completed":
        # 场景 H/I：已由他人（或自己）完成 → 明确业务结果，不产生重复事实
        rep = db.execute(
            select(ProductionReport).where(ProductionReport.task_id == task.id)
        ).scalars().first()
        raise BusinessError(
            "ALREADY_COMPLETED",
            "该构件此工序已由他人登记完成",
            409,
            extra={"report_id": rep.id if rep else None, "task_id": task.id},
        )

    now = _naive(occurred_at)
    ac = db.get(ActualComponent, task.actual_component_id)
    was_not_started = ac.production_status == "not_started"

    # 6. 写入报工事实（只追加）
    report = ProductionReport(
        task_id=task.id,
        actual_component_id=ac.id,
        route_template_step_id=task.route_template_step_id,
        operation_snapshot=_op_name(db, task.route_template_step_id),
        execute_team_id=task.execute_team_id,
        channel="scan" if qr_code else "manual",
        action_key=ak,
        client_token=client_token,
        occurred_at=now,
    )
    db.add(report)
    try:
        db.flush()  # 获取 report.id，并触发 client_token / (task_id,action_key) 唯一约束
    except IntegrityError:
        db.rollback()
        # 兜底：并发同动作（另一请求已先落库）或网络重试同令牌，均给出明确业务结果，
        # 绝不抛出裸 IntegrityError。
        existing = db.execute(
            select(ProductionReport).where(
                (ProductionReport.client_token == client_token)
                | (
                    (ProductionReport.task_id == task.id)
                    & (ProductionReport.action_key == ak)
                )
            )
        ).scalars().first()
        if existing is not None:
            if existing.client_token == client_token:
                # 同令牌重试 -> 幂等返回首次结果
                return _result_from_report(db, existing, idempotent=True, status="completed")
            # 不同令牌、同构件同工序动作 -> 并发已由他人完成
            raise BusinessError(
                "ALREADY_COMPLETED",
                "该构件此工序已由他人登记完成",
                409,
                extra={"report_id": existing.id, "task_id": task.id},
            )
        raise

    for wid in worker_ids:
        db.add(ProductionReportWorker(
            report_id=report.id,
            employee_id=wid,
            occurred_at=now,
            created_by=user_ctx.user_id,
        ))

    # 7. 任务状态机推进（pending -> in_progress -> completed）
    if task.status == "pending":
        task.status = "in_progress"
        db.add(TaskEvent(task_id=task.id, event_type="start", occurred_at=now))
    task.status = "completed"
    task.actual_end = now
    db.add(TaskEvent(task_id=task.id, event_type="complete", occurred_at=now))

    # 8. 构件生产状态机推进
    if was_not_started:
        ac.production_status = "in_production"
        db.add(ActualComponentEvent(actual_component_id=ac.id, event_type="start", occurred_at=now))
    total = db.execute(
        select(func.count())
        .select_from(ProductionTask)
        .where(ProductionTask.actual_component_id == ac.id)
    ).scalar() or 0
    done = db.execute(
        select(func.count())
        .select_from(ProductionTask)
        .where(ProductionTask.actual_component_id == ac.id, ProductionTask.status == "completed")
    ).scalar() or 0
    if total > 0 and total == done:
        ac.production_status = "production_completed"
        db.add(ActualComponentEvent(actual_component_id=ac.id, event_type="complete", occurred_at=now))

    db.commit()
    return _result_from_report(db, report, idempotent=False, status="completed")
