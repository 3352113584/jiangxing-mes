"""Phase 4 Sprint 1 — PC 生产任务分配路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.task import AssignRequest, PendingComponentOut, ReassignRequest, TaskOut
from app.services import task_service
from app.services.auth_service import UserContext
from app.services.errors import BusinessError

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/pending-components", response_model=list[PendingComponentOut])
def pending_components(
    subproject_id: int = Query(..., description="子项目 id"),
    step_id: int = Query(..., description="route_template_step id（工序步骤）"),
    db: Session = Depends(get_db),
):
    """按 子项目 / 工序 查看待分配构件（尚无该工序任务的 actual_component）。"""
    rows = task_service.list_pending_components(db, subproject_id, step_id)
    return [PendingComponentOut(**r) for r in rows]


@router.post("/assign")
def assign(req: AssignRequest, ctx: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    """批量分配执行班组。split=equal 系统辅助平均分配；split=manual 按 manual_team_map。"""
    return task_service.assign_tasks(
        db,
        step_id=req.step_id,
        component_ids=req.component_ids,
        team_ids=req.team_ids,
        split=req.split,
        manual_team_map=req.manual_team_map,
        make_type=req.make_type,
        supplier_id=req.supplier_id,
        planned_start=req.planned_start,
        planned_end=req.planned_end,
        actor_user_id=ctx.user_id,
    )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    subproject_id: Optional[int] = None,
    step_id: Optional[int] = None,
    operation_type_id: Optional[int] = None,
    team_id: Optional[int] = None,
    status: Optional[str] = None,
    main_project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    rows = task_service.list_tasks(
        db,
        subproject_id=subproject_id,
        step_id=step_id,
        operation_type_id=operation_type_id,
        team_id=team_id,
        status=status,
        main_project_id=main_project_id,
    )
    return [TaskOut(**r) for r in rows]


@router.patch("/{task_id}/reassign")
def reassign(task_id: int, req: ReassignRequest, ctx: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    """人工调整执行班组（仅未产生生产履历前允许；已登记/已完成任务受历史保护）。"""
    return task_service.reassign_task(db, task_id, req.new_team_id, ctx.user_id)
