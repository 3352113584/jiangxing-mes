"""M-P4-3 价格版本管理（关闭旧版本 + 新建版本；历史价格不变更、不覆盖）。

设计约束（任务书 §二 / §六）：
- 同一 project_operation 只能有一个开放当前版本；
- 生效区间不重叠；
- effective_from <= 当前日期 的已生效历史版本不得 UPDATE/DELETE（T-17 兜底）；
- 改价 = 关闭旧当前版本 + 新建版本（先关后建，避免区间重叠）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.eng import ProjectOperation, ProjectOperationPrice


def create_project_operation(
    db: Session,
    *,
    main_project_id: Optional[int] = None,
    subproject_id: Optional[int] = None,
    project_operation_code: str,
    operation_type_id: Optional[int] = None,
    custom_name: Optional[str] = None,
    default_team_id: Optional[int] = None,
    is_active: bool = True,
) -> ProjectOperation:
    """建立项目工序稳定身份（标准工序 operation_type_id / 自定义工序 custom_name 二选一）。

    default_team_id 仅用于未来任务生成默认班组，绝不参与实际成本归属。"""
    if (operation_type_id is None) == (custom_name is None):
        raise ValueError("operation_type_id 与 custom_name 必须且只能提供一个")
    po = ProjectOperation(
        main_project_id=main_project_id,
        subproject_id=subproject_id,
        project_operation_code=project_operation_code,
        operation_type_id=operation_type_id,
        custom_name=custom_name,
        default_team_id=default_team_id,
        is_active=is_active,
    )
    db.add(po)
    db.flush()
    return po


def _next_version_no(db: Session, project_operation_id: int) -> int:
    n = db.execute(
        select(func.max(ProjectOperationPrice.version_no)).where(
            ProjectOperationPrice.project_operation_id == project_operation_id
        )
    ).scalar()
    return (n or 0) + 1


def create_price_version(
    db: Session,
    *,
    project_operation_id: int,
    price: float,
    price_basis: str,
    effective_from: date,
    effective_to: Optional[date] = None,
    approved_by: Optional[int] = None,
    close_old: bool = True,
    occurred_at: Optional[datetime] = None,
) -> ProjectOperationPrice:
    """新建价格版本。默认先关闭旧当前版本（设置 effective_to=新版本 effective_from, is_current=False），再插入新版本。

    不变更/覆盖任何历史版本；区间重叠、双当前、已生效历史修改由 T-17 触发器兜底拒绝。"""
    if close_old:
        cur = db.execute(
            select(ProjectOperationPrice).where(
                ProjectOperationPrice.project_operation_id == project_operation_id,
                ProjectOperationPrice.is_current == True,  # noqa: E712
            )
        ).scalars().first()
        if cur is not None:
            cur.effective_to = effective_from  # exclusive end，与下一版本无缝衔接
            cur.is_current = False
            db.add(cur)
            db.flush()

    pop = ProjectOperationPrice(
        project_operation_id=project_operation_id,
        version_no=_next_version_no(db, project_operation_id),
        price=price,
        price_basis=price_basis,
        effective_from=effective_from,
        effective_to=effective_to,
        is_current=True,
        approved_by=approved_by,
        occurred_at=occurred_at or datetime.now(),
    )
    db.add(pop)
    db.flush()
    return pop
