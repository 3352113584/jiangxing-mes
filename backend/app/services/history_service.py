"""Phase 4 Sprint 1 — 生产履历/登记结果查询服务。

最小可用：项目/子项目/班组/工序/日期/构件基础筛选；先保证数据正确，不追求复杂报表。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.eng import RouteTemplateStep
from app.db.models.md import Employee, MainProject, Subproject, Team, UserAccount
from app.db.models.prod_component import ActualComponent
from app.db.models.prod_plan import (
    ProductionReport,
    ProductionReportWorker,
    ProductionTask,
)
from app.db.models.ref import OperationType


def _base_stmt(f):
    stmt = (
        select(
            ProductionReport.id,
            ProductionReport.task_id,
            ProductionReport.channel,
            ProductionReport.occurred_at,
            ProductionReport.recorded_at,
            ProductionReport.created_by,
            ProductionTask.status,
            MainProject.project_code,
            MainProject.name.label("mp_name"),
            Subproject.subproject_code,
            Subproject.name.label("sp_name"),
            ActualComponent.component_no,
            ActualComponent.instance_sequence,
            ActualComponent.id.label("ac_id"),
            OperationType.name.label("op_name"),
            RouteTemplateStep.step_no,
            Team.name.label("team_name"),
        )
        .join(ProductionTask, ProductionTask.id == ProductionReport.task_id)
        .join(ActualComponent, ActualComponent.id == ProductionReport.actual_component_id)
        .join(Subproject, Subproject.id == ActualComponent.subproject_id)
        .join(MainProject, MainProject.id == Subproject.main_project_id)
        .join(RouteTemplateStep, RouteTemplateStep.id == ProductionReport.route_template_step_id)
        .join(OperationType, OperationType.id == RouteTemplateStep.operation_type_id)
        .join(Team, Team.id == ProductionReport.execute_team_id)
    )
    if f.main_project_id is not None:
        stmt = stmt.where(MainProject.id == f.main_project_id)
    if f.subproject_id is not None:
        stmt = stmt.where(Subproject.id == f.subproject_id)
    if f.team_id is not None:
        stmt = stmt.where(Team.id == f.team_id)
    if f.step_id is not None:
        stmt = stmt.where(RouteTemplateStep.id == f.step_id)
    if f.operation_type_id is not None:
        stmt = stmt.where(OperationType.id == f.operation_type_id)
    if f.date_from is not None:
        stmt = stmt.where(ProductionReport.occurred_at >= f.date_from)
    if f.date_to is not None:
        stmt = stmt.where(ProductionReport.occurred_at <= f.date_to)
    if f.component_no is not None:
        stmt = stmt.where(ActualComponent.component_no == f.component_no)
    return stmt


def query_reports(db: Session, f) -> tuple[list[dict], int]:
    base = _base_stmt(f)
    total = db.execute(base.with_only_columns(func.count())).scalar() or 0
    rows = (
        db.execute(
            base.order_by(ProductionReport.occurred_at.desc(), ProductionReport.id.desc())
            .offset((f.page - 1) * f.page_size)
            .limit(f.page_size)
        )
        .mappings()
        .all()
    )
    report_ids = [r["id"] for r in rows]
    workers_map: dict[int, list[str]] = {}
    if report_ids:
        wrows = db.execute(
            select(ProductionReportWorker.report_id, Employee.name)
            .join(Employee, Employee.id == ProductionReportWorker.employee_id)
            .where(ProductionReportWorker.report_id.in_(report_ids))
        ).all()
        for rid, wname in wrows:
            workers_map.setdefault(rid, []).append(wname)
    created_bys = {r["created_by"] for r in rows if r["created_by"]}
    user_map: dict[int, str] = {}
    if created_bys:
        urows = db.execute(
            select(UserAccount.id, UserAccount.username).where(UserAccount.id.in_(created_bys))
        ).all()
        user_map = {u[0]: u[1] for u in urows}

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "report_id": r["id"],
                "task_id": r["task_id"],
                "main_project_code": r["project_code"],
                "main_project_name": r["mp_name"],
                "subproject_code": r["subproject_code"],
                "subproject_name": r["sp_name"],
                "component_no": r["component_no"],
                "instance_sequence": r["instance_sequence"],
                "actual_component_id": r["ac_id"],
                "operation_type_name": r["op_name"],
                "step_no": r["step_no"],
                "execute_team_name": r["team_name"],
                "workers": workers_map.get(r["id"], []),
                "registered_by": user_map.get(r["created_by"]) if r["created_by"] else None,
                "channel": r["channel"],
                "occurred_at": r["occurred_at"],
                "recorded_at": r["recorded_at"],
                "task_status": r["status"],
            }
        )
    return out, total
