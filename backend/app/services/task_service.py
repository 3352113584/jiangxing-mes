"""Phase 4 Sprint 1 — 生产任务分配服务。

职责：
- 查询某工序下「尚未分配任务」的构件（actual_component 一行一实体）；
- 批量分配执行班组到 production_task（身份 (actual_component_id, route_template_step_id, attempt)）；
- 系统辅助平均分配（equal：按「数量+重量」贪心均衡）+ 人工调整（manual）；
- 人工调整执行班组（reassign），但已产生生产履历的任务禁止篡改历史。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.eng import RouteTemplateStep
from app.db.models.md import MainProject, Subproject, Team
from app.db.models.prod_component import ActualComponent, ComponentListItem, QrCodeRegistry
from app.db.models.prod_plan import ProductionReport, ProductionTask
from app.db.models.ref import OperationType
from app.services.errors import BusinessError


# ---------------------------------------------------------------------------
# 查询：待分配构件
# ---------------------------------------------------------------------------
def list_pending_components(db: Session, subproject_id: int, step_id: int) -> list[dict]:
    rows = db.execute(
        select(
            ActualComponent.id.label("actual_component_id"),
            ActualComponent.component_no,
            ActualComponent.instance_sequence,
            Subproject.id.label("subproject_id"),
            Subproject.subproject_code,
            Subproject.main_project_id,
            MainProject.project_code.label("main_project_code"),
            MainProject.name.label("main_project_name"),
            func.coalesce(ActualComponent.actual_weight, ComponentListItem.theoretical_weight),
        )
        .join(Subproject, Subproject.id == ActualComponent.subproject_id)
        .join(MainProject, MainProject.id == Subproject.main_project_id)
        .join(ComponentListItem, ComponentListItem.id == ActualComponent.component_list_item_id)
        .outerjoin(
            ProductionTask,
            (ProductionTask.actual_component_id == ActualComponent.id)
            & (ProductionTask.route_template_step_id == step_id),
        )
        .where(
            ActualComponent.subproject_id == subproject_id,
            ProductionTask.id.is_(None),
        )
        .order_by(ActualComponent.component_no, ActualComponent.instance_sequence)
    ).mappings().all()
    return [
        {
            "actual_component_id": r["actual_component_id"],
            "component_no": r["component_no"],
            "instance_sequence": r["instance_sequence"],
            "subproject_id": r["subproject_id"],
            "subproject_code": r["subproject_code"],
            "main_project_id": r["main_project_id"],
            "main_project_code": r["main_project_code"],
            "main_project_name": r["main_project_name"],
            "weight": float(r["weight"]) if r["weight"] is not None else None,
            "has_task_for_step": False,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 分配：批量建立 production_task
# ---------------------------------------------------------------------------
def _build_team_map(
    db: Session,
    component_ids: list[int],
    team_ids: list[int],
    split: str,
    manual_team_map: Optional[dict],
) -> dict[int, int]:
    # 取构件权重（actual_weight 优先，缺省按 1.0=每件，使无重量时按数量均衡）
    weights = {}
    for cid in component_ids:
        ac = db.get(ActualComponent, cid)
        cli = db.get(ComponentListItem, ac.component_list_item_id) if ac else None
        w = ac.actual_weight if (ac and ac.actual_weight is not None) else None
        if w is None and cli is not None and cli.theoretical_weight is not None:
            w = float(cli.theoretical_weight)
        weights[cid] = float(w) if w is not None else 1.0

    if split == "manual":
        if not manual_team_map:
            raise BusinessError("BAD_REQUEST", "manual 模式必须提供 manual_team_map", 400)
        for cid in component_ids:
            if cid not in manual_team_map:
                raise BusinessError("BAD_REQUEST", f"构件 {cid} 缺少目标班组", 400)
        return {cid: manual_team_map[cid] for cid in component_ids}

    # equal：按重量贪心均衡（重量相同时退化为按数量均衡）
    load = {t: 0.0 for t in team_ids}
    assignment: dict[int, int] = {}
    for cid in sorted(component_ids, key=lambda c: weights[c], reverse=True):
        t = min(team_ids, key=lambda x: load[x])
        assignment[cid] = t
        load[t] += weights[cid]
    return assignment


def assign_tasks(
    db: Session,
    step_id: int,
    component_ids: list[int],
    team_ids: list[int],
    split: str = "equal",
    manual_team_map: Optional[dict] = None,
    make_type: str = "inhouse",
    supplier_id: Optional[int] = None,
    planned_start=None,
    planned_end=None,
    actor_user_id: Optional[int] = None,
) -> list[dict]:
    # 校验 step 存在
    step = db.get(RouteTemplateStep, step_id)
    if step is None:
        raise BusinessError("STEP_NOT_FOUND", "工序步骤不存在", 404)
    team_map = _build_team_map(db, component_ids, team_ids, split, manual_team_map)

    created: list[dict] = []
    for cid, tid in team_map.items():
        # 幂等：同一 (构件, 工序, attempt=1) 已存在任务则跳过
        exists = db.execute(
            select(ProductionTask.id).where(
                ProductionTask.actual_component_id == cid,
                ProductionTask.route_template_step_id == step_id,
                ProductionTask.attempt == 1,
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        task = ProductionTask(
            actual_component_id=cid,
            route_template_step_id=step_id,
            attempt=1,
            execute_team_id=tid,
            make_type=make_type,
            supplier_id=supplier_id if make_type == "outsource" else None,
            planned_start=planned_start,
            planned_end=planned_end,
            status="pending",
        )
        db.add(task)
        created.append(
            {"actual_component_id": cid, "team_id": tid, "task": task}
        )
    db.commit()
    # 刷新并返回摘要
    out = []
    for item in created:
        t = item["task"]
        db.refresh(t)
        out.append(
            {
                "task_id": t.id,
                "actual_component_id": t.actual_component_id,
                "execute_team_id": t.execute_team_id,
                "step_id": t.route_template_step_id,
                "status": t.status,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 任务列表 / 人工调整
# ---------------------------------------------------------------------------
def list_tasks(
    db: Session,
    *,
    subproject_id: Optional[int] = None,
    step_id: Optional[int] = None,
    operation_type_id: Optional[int] = None,
    team_id: Optional[int] = None,
    status: Optional[str] = None,
    main_project_id: Optional[int] = None,
) -> list[dict]:
    stmt = (
        select(
            ProductionTask.id.label("task_id"),
            ProductionTask.actual_component_id,
            ActualComponent.component_no,
            ActualComponent.instance_sequence,
            ActualComponent.subproject_id,
            Subproject.subproject_code,
            ProductionTask.route_template_step_id.label("step_id"),
            RouteTemplateStep.step_no,
            RouteTemplateStep.operation_type_id,
            OperationType.name.label("operation_type_name"),
            ProductionTask.attempt,
            ProductionTask.execute_team_id,
            Team.name.label("team_name"),
            ProductionTask.make_type,
            ProductionTask.status,
            ProductionTask.planned_start,
            ProductionTask.planned_end,
            ProductionTask.actual_start,
            ProductionTask.actual_end,
            select(ProductionReport.id)
            .where(ProductionReport.task_id == ProductionTask.id)
            .exists()
            .label("has_report"),
        )
        .join(ActualComponent, ActualComponent.id == ProductionTask.actual_component_id)
        .join(Subproject, Subproject.id == ActualComponent.subproject_id)
        .join(RouteTemplateStep, RouteTemplateStep.id == ProductionTask.route_template_step_id)
        .join(OperationType, OperationType.id == RouteTemplateStep.operation_type_id)
        .join(Team, Team.id == ProductionTask.execute_team_id)
    )
    if main_project_id is not None:
        stmt = stmt.where(Subproject.main_project_id == main_project_id)
    if subproject_id is not None:
        stmt = stmt.where(ActualComponent.subproject_id == subproject_id)
    if step_id is not None:
        stmt = stmt.where(ProductionTask.route_template_step_id == step_id)
    if operation_type_id is not None:
        stmt = stmt.where(RouteTemplateStep.operation_type_id == operation_type_id)
    if team_id is not None:
        stmt = stmt.where(ProductionTask.execute_team_id == team_id)
    if status is not None:
        stmt = stmt.where(ProductionTask.status == status)
    rows = db.execute(stmt.order_by(ProductionTask.id)).mappings().all()
    return [dict(r) for r in rows]


def reassign_task(db: Session, task_id: int, new_team_id: int, actor_user_id: Optional[int] = None) -> dict:
    task = db.get(ProductionTask, task_id)
    if task is None:
        raise BusinessError("TASK_NOT_FOUND", "任务不存在", 404)
    if db.get(Team, new_team_id) is None:
        raise BusinessError("TEAM_NOT_FOUND", "目标班组不存在", 404)
    # 历史保护：已产生生产履历（含已完成）的任务不可篡改执行班组
    has_report = db.execute(
        select(ProductionReport.id).where(ProductionReport.task_id == task_id)
    ).scalar_one_or_none()
    if has_report is not None or task.status == "completed":
        raise BusinessError(
            "HISTORY_PROTECTED",
            "已产生生产履历的任务不可篡改历史执行班组",
            409,
        )
    task.execute_team_id = new_team_id
    db.commit()
    db.refresh(task)
    return {
        "task_id": task.id,
        "execute_team_id": task.execute_team_id,
        "status": task.status,
    }


# ---------------------------------------------------------------------------
# Android「我的任务」：当前用户主属班组被指派、未完成的任务
# ---------------------------------------------------------------------------
def list_my_tasks(db: Session, primary_team_id: int) -> list[dict]:
    rows = db.execute(
        select(
            ProductionTask.id,
            ProductionTask.actual_component_id,
            ActualComponent.component_no,
            ActualComponent.instance_sequence,
            QrCodeRegistry.qr_code,
            Subproject.subproject_code,
            MainProject.project_code.label("main_project_code"),
            RouteTemplateStep.step_no,
            OperationType.name.label("operation_type_name"),
            Team.name.label("team_name"),
            ProductionTask.status,
        )
        .join(ActualComponent, ActualComponent.id == ProductionTask.actual_component_id)
        .join(QrCodeRegistry, QrCodeRegistry.id == ActualComponent.qr_code_id)
        .join(Subproject, Subproject.id == ActualComponent.subproject_id)
        .join(MainProject, MainProject.id == Subproject.main_project_id)
        .join(RouteTemplateStep, RouteTemplateStep.id == ProductionTask.route_template_step_id)
        .join(OperationType, OperationType.id == RouteTemplateStep.operation_type_id)
        .join(Team, Team.id == ProductionTask.execute_team_id)
        .where(
            ProductionTask.execute_team_id == primary_team_id,
            ProductionTask.status.in_(["pending", "in_progress"]),
        )
        .order_by(ProductionTask.id)
    ).mappings().all()
    return [dict(r) for r in rows]
