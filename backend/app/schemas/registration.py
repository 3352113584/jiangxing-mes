"""Phase 4 Sprint 1 — 构件登记（Android/PC 共用）相关 Schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MyTaskOut(BaseModel):
    """Android「我的任务」：当前用户主属班组被指派、且未完成的任务。"""

    task_id: int
    actual_component_id: int
    component_no: str
    instance_sequence: int
    qr_code: str
    subproject_code: str
    main_project_code: str
    step_no: int
    operation_type_name: str
    team_name: str
    status: str


class RegisterRequest(BaseModel):
    """构件生产工序登记。

    两种入口二选一：qr_code（扫码）或 task_id（任务列表选择）。
    幂等：client_token 为网络层幂等令牌（必填，重试复用同一令牌）；
    action_key 为业务动作幂等键（可选，缺省由服务端按 task 推导）。
    """

    qr_code: Optional[str] = Field(None, description="扫码入口：构件二维码")
    task_id: Optional[int] = Field(None, description="任务列表选择入口：直接指定任务")
    client_token: str = Field(..., description="客户端生成的网络幂等令牌（UUID），重试必须复用")
    action_key: Optional[str] = Field(None, description="业务动作幂等键；缺省由服务端推导为 complete:<task_id>")
    worker_ids: list[int] = Field(..., min_length=1, description="实际作业人员 employee_id 列表")
    occurred_at: Optional[datetime] = Field(None, description="作业发生时间；缺省取服务器时间")


class RegisterResult(BaseModel):
    report_id: Optional[int] = None
    task_id: int
    actual_component_id: int
    component_no: str
    instance_sequence: int
    operation_type_name: str
    team_name: str
    status: str  # completed | already_completed
    idempotent: bool = False  # True=本次为幂等返回（重复提交命中）
    message: str = ""
