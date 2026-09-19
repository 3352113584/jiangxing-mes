"""Phase 4 Sprint 1 — PC 生产履历/登记结果路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.history import ReportFilter, ReportOut
from app.services import history_service

router = APIRouter(prefix="/api/production-reports", tags=["production-reports"])


@router.get("")
def list_reports(
    main_project_id: Optional[int] = None,
    subproject_id: Optional[int] = None,
    team_id: Optional[int] = None,
    step_id: Optional[int] = None,
    operation_type_id: Optional[int] = None,
    component_no: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """生产登记结果/履历查询，支持 项目/子项目/班组/工序/日期/构件 基础筛选。"""
    f = ReportFilter(
        main_project_id=main_project_id,
        subproject_id=subproject_id,
        team_id=team_id,
        step_id=step_id,
        operation_type_id=operation_type_id,
        component_no=component_no,
        date_from=_parse(date_from),
        date_to=_parse(date_to),
        page=page,
        page_size=page_size,
    )
    items, total = history_service.query_reports(db, f)
    return {"items": [ReportOut(**it) for it in items], "total": total}


def _parse(s: Optional[str]):
    if not s:
        return None
    from datetime import datetime

    return datetime.fromisoformat(s)
