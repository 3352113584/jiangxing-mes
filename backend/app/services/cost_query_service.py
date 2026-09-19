"""M-P4-3 只读成本查询入口（service 层封装 SQL 视图，不修改任何业务数据）。

视图语义见迁移 f0a1b2c3d4e5：
- eng.v_operation_cost_trial：生产任务级成本试算明细（5 计价口径 + 时间旅行 + 异常标记）
- eng.v_project_production_cost：项目→工序→班组→月 汇总（正常/返工/合计成本）

本服务仅做参数化 SELECT，供 API / 报表复用；所有函数只读。
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def _trial_where(clauses: list[str], params: dict, *, po=None, mp=None, sp=None, team=None, anomaly=None):
    if po is not None:
        clauses.append("project_operation_id = :po"); params["po"] = po
    if mp is not None:
        clauses.append("main_project_id = :mp"); params["mp"] = mp
    if sp is not None:
        clauses.append("subproject_id = :sp"); params["sp"] = sp
    if team is not None:
        clauses.append("execute_team_id = :team"); params["team"] = team
    if anomaly is not None:
        clauses.append("anomaly_status = :anomaly"); params["anomaly"] = anomaly


def trial_rows(
    db: Session,
    *,
    project_operation_id: Optional[int] = None,
    main_project_id: Optional[int] = None,
    subproject_id: Optional[int] = None,
    execute_team_id: Optional[int] = None,
    anomaly_status: Optional[str] = None,
    only_rework: Optional[bool] = None,
) -> list[dict]:
    """返回 v_operation_cost_trial 明细（按 occurred_at, task_id 排序）。"""
    clauses = []
    params: dict = {}
    _trial_where(clauses, params, po=project_operation_id, mp=main_project_id,
                 sp=subproject_id, team=execute_team_id, anomaly=anomaly_status)
    if only_rework is True:
        clauses.append("is_rework")
    elif only_rework is False:
        clauses.append("NOT is_rework")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.execute(
        text(f"SELECT * FROM eng.v_operation_cost_trial{where} ORDER BY occurred_at, task_id"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def project_cost_summary(
    db: Session,
    *,
    main_project_id: Optional[int] = None,
    subproject_id: Optional[int] = None,
    project_operation_id: Optional[int] = None,
    execute_team_id: Optional[int] = None,
) -> list[dict]:
    """返回 v_project_production_cost 汇总行（按 project/subproject/po/team/month）。"""
    clauses = []
    params: dict = {}
    if main_project_id is not None:
        clauses.append("main_project_id = :mp"); params["mp"] = main_project_id
    if subproject_id is not None:
        clauses.append("subproject_id = :sp"); params["sp"] = subproject_id
    if project_operation_id is not None:
        clauses.append("project_operation_id = :po"); params["po"] = project_operation_id
    if execute_team_id is not None:
        clauses.append("execute_team_id = :team"); params["team"] = execute_team_id
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.execute(
        text(f"SELECT * FROM eng.v_project_production_cost{where} "
             f"ORDER BY main_project_id, subproject_id, project_operation_id, execute_team_id, month"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]
