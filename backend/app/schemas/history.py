"""Phase 4 Sprint 1 — 生产履历/登记结果查询 Schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReportOut(BaseModel):
    report_id: int
    task_id: int
    main_project_code: str
    main_project_name: str
    subproject_code: str
    subproject_name: str
    component_no: str
    instance_sequence: int
    actual_component_id: int
    operation_type_name: str
    step_no: int
    execute_team_name: str
    workers: list[str]  # 作业人员姓名列表
    registered_by: Optional[str] = None
    channel: str
    occurred_at: datetime
    recorded_at: datetime
    task_status: str


class ReportFilter(BaseModel):
    main_project_id: Optional[int] = None
    subproject_id: Optional[int] = None
    team_id: Optional[int] = None
    step_id: Optional[int] = None
    operation_type_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    component_no: Optional[str] = None
    page: int = 1
    page_size: int = 50
