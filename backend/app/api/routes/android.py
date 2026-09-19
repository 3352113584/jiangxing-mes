"""Phase 4 Sprint 1 — Android 车间端路由（仅构件登记，契约第七章冻结边界）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.registration import MyTaskOut, RegisterRequest, RegisterResult
from app.services import registration_service
from app.services.auth_service import UserContext
from app.services.errors import BusinessError

router = APIRouter(prefix="/api/android", tags=["android"])


@router.get("/my-tasks", response_model=list[MyTaskOut])
def my_tasks(ctx: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户主属班组被指派、未完成的任务（不含项目全部构件）。"""
    if not ctx.primary_team_id:
        raise BusinessError("NO_PRIMARY_TEAM", "当前账号无主属班组", 403)
    from app.services import task_service

    rows = task_service.list_my_tasks(db, ctx.primary_team_id)
    return [
        MyTaskOut(
            task_id=r["id"],
            actual_component_id=r["actual_component_id"],
            component_no=r["component_no"],
            instance_sequence=r["instance_sequence"],
            qr_code=r["qr_code"],
            subproject_code=r["subproject_code"],
            main_project_code=r["main_project_code"],
            step_no=r["step_no"],
            operation_type_name=r["operation_type_name"],
            team_name=r["team_name"],
            status=r["status"],
        )
        for r in rows
    ]


@router.post("/register", response_model=RegisterResult)
def register(req: RegisterRequest, ctx: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    """构件生产工序登记（扫码 OR 任务列表选择）。服务端强制幂等/并发/状态机。"""
    res = registration_service.register(
        db,
        user_ctx=ctx,
        qr_code=req.qr_code,
        task_id=req.task_id,
        client_token=req.client_token,
        action_key=req.action_key,
        worker_ids=req.worker_ids,
        occurred_at=req.occurred_at,
    )
    return RegisterResult(**res)
