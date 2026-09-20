"""V1.2 劳务结算（最小口径）服务 — 落地 M5 / M7 / M8 / M9 / M10。

设计纪律（源自大王第2轮整改指令，与《班组能力-构件类型-工艺模板-劳务计价业务设计审查报告》一致）：
- M5 标准模板→项目实例：项目路线由标准模板"采用/复制"而来，项目实例修改不反向影响标准模板。
- M7 计价来源优先级：项目价(project_operation_price 当前版本) > 基础价(labor_pricing_rule_version 当前版本)
  > MISSING_PRICE（以 None 表示，**绝不**以 0 兜底）。
- M8 计价资格 chargeability：chargeable=班组有权计酬；non_chargeable=班组自身责任不予计酬
  （如 A 自责返工）。可区分班组责任 / 设计变更 / 材料问题 / 前道工序 / 其他非班组责任。
- M9 chargeable 过滤：production_report 绝不等于劳务结算；本服务是只读匹配层。
  v_project_production_cost / v_operation_cost_trial 为"生产成本/试算"视图，非最终结算事实。
- M10 三个返工场景（A 自责→A 返工→A 只计 1 次；B 自责→A 返工→A=1,B=1；设计变更→B 返工→B 正常计）
  必须经自动化测试验证最终金额。
- M11 历史不可变：价格/模板/班组能力/构件类型字典改动不得改写已发生历史；
  本服务按 occurred_at 时间旅行匹配 current 版本，不回写历史。

本模块使用 psycopg 直连（与 tests/db 的 B 构造器一致），便于在真实 PG 上做最小口径测试。
后续若接入 FastAPI 可用 SQLAlchemy Session 包一层，逻辑不变。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

# 计价来源解析时 MISSING_PRICE 的哨兵：返回 None，上层明确区分"无价"与"0 元"。
MISSING_PRICE = None


def _resolve_base_unit_price(
    conn,
    *,
    component_type_id: int,
    operation_type_id: Optional[int] = None,
    project_operation_id: Optional[int] = None,
    team_id: Optional[int] = None,
    effective_date: date,
) -> Optional[float]:
    """M6 基础价：labor_pricing_rule(构件类型×工序×可选班组) 的当前生效版本单价。

    班组精确价优先于通用价（applicable_team_id 为空=通用）。"""
    row = conn.execute(
        """
        SELECT v.unit_price
        FROM eng.labor_pricing_rule r
        JOIN eng.labor_pricing_rule_version v ON v.rule_id = r.id
        WHERE r.component_type_id = %s
          AND ((r.operation_type_id = %s AND r.project_operation_id IS NULL)
               OR (r.project_operation_id = %s AND r.operation_type_id IS NULL))
          AND (r.applicable_team_id IS NULL OR r.applicable_team_id = %s)
          AND r.is_active
          AND v.effective_from <= %s
          AND (v.effective_to IS NULL OR v.effective_to >= %s)
        ORDER BY (r.applicable_team_id IS NOT NULL) DESC, v.effective_from DESC
        LIMIT 1
        """,
        (component_type_id, operation_type_id, project_operation_id, team_id,
         effective_date, effective_date),
    ).fetchone()
    return float(row[0]) if row else None


def _resolve_project_unit_price(
    conn, *, project_operation_id: int, effective_date: date
) -> Optional[float]:
    """M-P4-3 项目价：project_operation_price 当前版本（按 occurred_at 时间旅行）。"""
    row = conn.execute(
        """
        SELECT price
        FROM eng.project_operation_price p
        WHERE p.project_operation_id = %s
          AND p.effective_from <= %s
          AND (p.effective_to IS NULL OR p.effective_to >= %s)
        ORDER BY p.effective_from DESC
        LIMIT 1
        """,
        (project_operation_id, effective_date, effective_date),
    ).fetchone()
    return float(row[0]) if row else None


def resolve_labor_unit_price(
    conn,
    *,
    component_type_id: int,
    operation_type_id: Optional[int] = None,
    project_operation_id: Optional[int] = None,
    team_id: Optional[int] = None,
    project_operation_id_override: Optional[int] = None,
    effective_date: date,
) -> Optional[float]:
    """M7 计价来源解析：项目价 > 基础价 > MISSING_PRICE(None)。绝不以 0 兜底。"""
    if project_operation_id_override is not None:
        p = _resolve_project_unit_price(
            conn, project_operation_id=project_operation_id_override, effective_date=effective_date
        )
        if p is not None:
            return p
    return _resolve_base_unit_price(
        conn,
        component_type_id=component_type_id,
        operation_type_id=operation_type_id,
        project_operation_id=project_operation_id,
        team_id=team_id,
        effective_date=effective_date,
    )


def classify_chargeability(
    responsibility_kind: Optional[str],
    is_rework: bool,
    responsible_team_id: Optional[int] = None,
    execute_team_id: Optional[int] = None,
) -> str:
    """计价资格判定（第 4 轮验收：以 responsibility_kind 为唯一权威来源，彻底分离"责任/执行/计价"）。

    规则与 eng.v_operation_cost_trial 的 effective_chargeability 完全一致：
    - 非返工（正常作业）                          → 'chargeable'
    - responsibility_kind = PENDING 或 NULL（无依据）→ 'non_chargeable'（不可结算，不默认放行）
    - responsibility_kind = TEAM 且 责任班组 == 执行班组（自责返工）→ 'non_chargeable'（不重复计）
    - responsibility_kind = TEAM 且 责任班组 != 执行班组（他人/前道工序责任）→ 'chargeable'（执行方计酬）
    - responsibility_kind = NON_TEAM（图纸/材料/前道工序/客户变更等外部责任）→ 'chargeable'（执行方计酬）

    说明：
    - responsibility_kind 是业务基于明确责任判定显式写入的"责任判定结果"，不再由异常分类推导，
      也不再单凭 responsible_team_id != execute_team_id 猜测责任（那是事实关系，非充分计价条件）。
    - rework_order.chargeability（stored）只是记录/缓存结果，不可绕过上述责任判定成为第二套规则。
    """
    if not is_rework:
        return "chargeable"
    if responsibility_kind == "PENDING" or responsibility_kind is None:
        return "non_chargeable"
    if responsibility_kind == "TEAM":
        if responsible_team_id is not None and execute_team_id is not None:
            return "non_chargeable" if responsible_team_id == execute_team_id else "chargeable"
        # TEAM 但缺责任/执行班组（DB 层 CK 已禁止 responsible_team_id 为 NULL）→ 保守不可结算
        return "non_chargeable"
    if responsibility_kind == "NON_TEAM":
        return "chargeable"
    return "non_chargeable"


def compute_task_labor_cost(
    conn,
    *,
    component_type_id: int,
    operation_type_id: Optional[int] = None,
    project_operation_id: Optional[int] = None,
    team_id: Optional[int] = None,
    project_operation_id_override: Optional[int] = None,
    effective_date: date,
    quantity: float,
    responsibility_kind: Optional[str] = None,
    is_rework: bool = False,
    responsible_team_id: Optional[int] = None,
    execute_team_id: Optional[int] = None,
) -> dict:
    """M9/M10 单任务劳务成本（最小口径）。

    返回 {'chargeable': bool, 'unit_price': float|None, 'amount': float|None}
      - chargeable=False（班组自身责任返工）       → amount = 0.0
      - unit_price=None（MISSING_PRICE，无基础价也无项目价）→ amount = None（绝不 0）
      - 否则                                       → amount = unit_price * quantity

    chargeable 由 classify_chargeability 基于 responsibility_kind（明确责任判定）推导，
    与 eng.v_operation_cost_trial 的 effective_chargeability 一致；stored chargeability 不参与。
    """
    chargeability = classify_chargeability(
        responsibility_kind,
        is_rework,
        responsible_team_id=responsible_team_id,
        execute_team_id=execute_team_id,
    )
    if chargeability == "non_chargeable":
        return {"chargeable": False, "unit_price": None, "amount": 0.0}
    unit_price = resolve_labor_unit_price(
        conn,
        component_type_id=component_type_id,
        operation_type_id=operation_type_id,
        project_operation_id=project_operation_id,
        team_id=team_id,
        project_operation_id_override=project_operation_id_override,
        effective_date=effective_date,
    )
    if unit_price is None:
        return {"chargeable": True, "unit_price": None, "amount": None}  # MISSING_PRICE
    return {"chargeable": True, "unit_price": unit_price, "amount": unit_price * quantity}


def adopt_standard_template(
    conn,
    *,
    standard_template_id: int,
    main_project_id: Optional[int] = None,
    subproject_id: Optional[int] = None,
    adopted_by: Optional[int] = None,
) -> int:
    """M5 标准模板→项目实例：复制标准模板头与工序行为项目路线（N-6 双归属仍满足）。

    项目实例修改不反向影响标准模板（来源追溯列 standard_template_id/version/adopted_by/at 落库）。
    """
    if (main_project_id is None) and (subproject_id is None):
        raise ValueError("路线必须挂主项目或子项目（N-6 双归属）")
    tpl = conn.execute(
        "SELECT version_no FROM eng.component_type_process_template WHERE id=%s",
        (standard_template_id,),
    ).fetchone()
    if tpl is None:
        raise ValueError(f"标准模板不存在: {standard_template_id}")
    version = tpl[0]
    rt_id = conn.execute(
        """
        INSERT INTO eng.route_template(main_project_id, subproject_id, name,
                                       standard_template_id, standard_template_version,
                                       adopted_by, adopted_at)
        VALUES (%s, %s, '采用标准模板', %s, %s, %s, now())
        RETURNING id
        """,
        (main_project_id, subproject_id, standard_template_id, version, adopted_by),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO eng.route_template_step(template_id, step_no, operation_type_id,
                                           project_operation_id, default_requirement, step_status)
        SELECT %s, step_no, operation_type_id, project_operation_id, default_requirement, step_status::enum_step_status
        FROM eng.component_type_process_step
        WHERE template_id = %s
        ORDER BY step_no
        """,
        (rt_id, standard_template_id),
    )
    return rt_id
