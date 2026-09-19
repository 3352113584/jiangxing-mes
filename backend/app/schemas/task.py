"""Phase 4 Sprint 1 — 生产任务分配相关 Schema。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PendingComponentOut(BaseModel):
    """待分配构件（按 actual_component 一行一实体；无 quantity 列，数量为件数）。"""

    actual_component_id: int
    component_no: str
    instance_sequence: int
    subproject_id: int
    subproject_code: str
    main_project_id: int
    main_project_code: str
    main_project_name: str
    # 单件重量（actual_weight 优先，回退清单理论重）。
    weight: float | None = None
    has_task_for_step: bool = False


class AssignRequest(BaseModel):
    """批量分配执行班组。

    - split='equal'：在 team_ids 间按“数量+重量”辅助平均分配（系统辅助，可后续人工调整）。
    - split='manual'：必须提供 manual_team_map（actual_component_id -> team_id）。
    """

    step_id: int = Field(..., description="route_template_step_id（工序步骤实例）")
    component_ids: list[int] = Field(..., min_length=1, description="待分配的 actual_component_id 列表")
    team_ids: list[int] = Field(..., min_length=1, description="目标执行班组 id 列表")
    split: str = Field("equal", pattern="^(equal|manual)$")
    manual_team_map: Optional[dict[int, int]] = None
    make_type: str = Field("inhouse", pattern="^(inhouse|outsource)$")
    supplier_id: Optional[int] = None
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None


class ReassignRequest(BaseModel):
    """人工调整：将某任务的执行班组改为 new_team_id（仅未产生生产履历前允许）。"""

    new_team_id: int


class TaskOut(BaseModel):
    task_id: int
    actual_component_id: int
    component_no: str
    instance_sequence: int
    subproject_id: int
    subproject_code: str
    step_id: int
    step_no: int
    operation_type_id: int
    operation_type_name: str
    attempt: int
    execute_team_id: int
    team_name: str
    make_type: str
    status: str
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    has_report: bool = False


class TaskFilter(BaseModel):
    main_project_id: Optional[int] = None
    subproject_id: Optional[int] = None
    step_id: Optional[int] = None
    operation_type_id: Optional[int] = None
    team_id: Optional[int] = None
    status: Optional[str] = None
    only_unassigned_for_step: Optional[int] = None  # 若提供 step_id 则忽略，列出该工序尚无任务的构件
