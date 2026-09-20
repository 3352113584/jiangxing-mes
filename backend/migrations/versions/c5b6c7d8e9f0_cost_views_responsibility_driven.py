"""劳务验收整改 c5：重写成本试算视图，使 responsible_team_id 真正进入计价链路（ORANGE-A / RED-A 收口）。

第 3 轮验收要求：chargeability 必须基于"明确责任判定结果"推导，而非异常分类；
responsible_team_id（责任班组）与 execute_team_id（执行班组）必须都能追溯且可不同，
金额判定必须真正使用 responsible_team_id，不得仅保存一个 chargeable 布尔就丢失责任依据。

视图推导规则（与 labor_settlement_service 保持一致）：
  effective_chargeability =
    - 非返工（正常作业）                          → 'chargeable'
    - 责任班组 == 执行班组（自责返工）            → 'non_chargeable'（不重复计）
    - 责任班组 != 执行班组（他人/前道工序责任）   → 'chargeable'（执行方计酬）
    - 责任班组 NULL 且 显式 chargeable（材料/图纸等外部原因）→ 'chargeable'
    - 责任班组 NULL 且无显式 chargeable（待确认/无依据）      → 'non_chargeable'
  pricing_basis 解释"为什么计价/为什么不计价"，使责任依据显式可见。

视图非数据，重写安全；不动历史迁移 f0a1b2c3d4e5 / c1 / c2 / c3 / c4。

Revision ID: c5b6c7d8e9f0
Revises: c4a5b6c7d8e9
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'c4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# c3 原视图定义（含 ro.chargeability 过滤），供 DOWNGRADE 还原到 c4 状态。
C3_VIEWS_SQL = r"""
DROP VIEW IF EXISTS eng.v_project_production_cost;
DROP VIEW IF EXISTS eng.v_operation_cost_trial;

CREATE VIEW eng.v_operation_cost_trial AS
WITH report_facts AS (
    SELECT
        pr.task_id,
        pr.occurred_at,
        pt.attempt,
        (pt.attempt > 1 OR pt.rework_of_task_id IS NOT NULL) AS is_rework,
        pt.execute_team_id,
        ac.id             AS actual_component_id,
        ac.component_no,
        ac.actual_weight,
        sp.main_project_id,
        sp.id             AS subproject_id,
        rts.id            AS route_template_step_id,
        rts.operation_type_id,
        rts.project_operation_id AS rts_po_id,
        ro.chargeability  AS chargeability,
        ro.responsible_team_id AS responsible_team_id,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'weight' THEN pm.value END), 0) AS w_val,
        COALESCE(SUM(CASE WHEN pm.measure_type IN ('cut_length','weld_length','mach_length') THEN pm.value END), 0) AS len_val,
        COALESCE(SUM(rw.work_hours), 0) AS hr_worker,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'hours' THEN pm.value END), 0) AS hr_val,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'hole_count' THEN pm.value END), 0) AS hole_val,
        CASE WHEN COUNT(CASE WHEN pm.measure_type = 'weight' THEN 1 END) > 0 THEN 1 ELSE 0 END AS has_w
    FROM prod.production_report pr
    JOIN prod.production_task pt      ON pt.id = pr.task_id
    JOIN eng.route_template_step rts  ON rts.id = pt.route_template_step_id
    JOIN prod.actual_component ac     ON ac.id = pt.actual_component_id
    JOIN md.subproject sp             ON sp.id = ac.subproject_id
    LEFT JOIN prod.production_measure pm ON pm.report_id = pr.id
    LEFT JOIN prod.production_report_worker rw ON rw.report_id = pr.id
    LEFT JOIN prod.rework_order ro    ON ro.id = pt.rework_order_id
    GROUP BY pr.id, pr.task_id, pr.occurred_at, pt.attempt, pt.rework_of_task_id, pt.execute_team_id,
             ac.id, ac.component_no, ac.actual_weight, sp.main_project_id, sp.id,
             rts.id, rts.operation_type_id, rts.project_operation_id,
             ro.chargeability, ro.responsible_team_id
),
po_resolved AS (
    SELECT rf.*, po.id AS project_operation_id, po.custom_name
    FROM report_facts rf
    LEFT JOIN LATERAL (
        SELECT po2.id, po2.custom_name
        FROM eng.project_operation po2
        WHERE po2.is_active
          AND ((rf.rts_po_id IS NOT NULL AND po2.id = rf.rts_po_id)
            OR (rf.rts_po_id IS NULL AND po2.operation_type_id = rf.operation_type_id
                AND (po2.main_project_id = rf.main_project_id OR po2.subproject_id = rf.subproject_id)))
        ORDER BY po2.id
        LIMIT 1
    ) po ON true
),
priced AS (
    SELECT r.*,
           MAX(r.occurred_at) OVER (PARTITION BY r.task_id) AS task_max_occurred_at,
           pop.price_basis,
           pop.price
    FROM po_resolved r
    LEFT JOIN LATERAL (
        SELECT x.price_basis, x.price
        FROM eng.project_operation_price x
        WHERE x.project_operation_id = r.project_operation_id
          AND x.effective_from <= r.occurred_at::date
          AND (x.effective_to IS NULL OR r.occurred_at::date < x.effective_to)
        ORDER BY x.effective_from DESC
        LIMIT 1
    ) pop ON true
),
task_piece_price AS (
    SELECT DISTINCT p.task_id, popp.price_basis, popp.price
    FROM priced p
    LEFT JOIN LATERAL (
        SELECT x.price_basis, x.price
        FROM eng.project_operation_price x
        WHERE x.project_operation_id = p.project_operation_id
          AND x.effective_from <= p.task_max_occurred_at::date
          AND (x.effective_to IS NULL OR p.task_max_occurred_at::date < x.effective_to)
        ORDER BY x.effective_from DESC
        LIMIT 1
    ) popp ON true
),
agg AS (
    SELECT
        task_id, actual_component_id, component_no, main_project_id, subproject_id,
        project_operation_id, operation_type_id, custom_name, execute_team_id,
        attempt, is_rework, price_basis, chargeability, responsible_team_id,
        MAX(occurred_at) AS occurred_at,
        SUM(CASE WHEN price_basis='weight' THEN CASE WHEN has_w=1 THEN w_val ELSE actual_weight END
                 WHEN price_basis='length' THEN len_val
                 WHEN price_basis='hour'   THEN COALESCE(hr_worker, hr_val)
                 WHEN price_basis='hole_count' THEN hole_val
                 ELSE 0 END) AS measure_value,
        SUM(CASE WHEN price IS NULL THEN 0 ELSE
              (CASE WHEN price_basis='weight' THEN CASE WHEN has_w=1 THEN w_val ELSE actual_weight END
                    WHEN price_basis='length' THEN len_val
                    WHEN price_basis='hour'   THEN COALESCE(hr_worker, hr_val)
                    WHEN price_basis='hole_count' THEN hole_val
                    ELSE 0 END) * price END) AS measured_amount,
        BOOL_OR(price IS NULL OR project_operation_id IS NULL) AS any_missing_price,
        BOOL_OR(execute_team_id IS NULL) AS any_missing_team,
        BOOL_OR(price_basis='weight' AND has_w=0 AND actual_weight IS NULL) AS w_missing,
        BOOL_OR(price_basis='weight' AND has_w=0 AND actual_weight IS NOT NULL) AS w_fallback,
        BOOL_OR(price_basis='length' AND len_val=0) AS len_missing,
        BOOL_OR(price_basis='hour' AND hr_worker=0 AND hr_val=0) AS hr_missing,
        BOOL_OR(price_basis='hole_count' AND hole_val=0) AS hole_missing,
        MAX(price) AS rep_price
    FROM priced
    GROUP BY task_id, actual_component_id, component_no, main_project_id, subproject_id,
             project_operation_id, operation_type_id, custom_name, execute_team_id,
             attempt, is_rework, price_basis, chargeability, responsible_team_id
)
SELECT
    a.task_id,
    a.actual_component_id,
    a.component_no,
    a.main_project_id,
    a.subproject_id,
    a.project_operation_id,
    a.operation_type_id,
    a.custom_name,
    a.execute_team_id,
    a.occurred_at,
    a.attempt,
    a.is_rework,
    a.price_basis,
    a.chargeability,
    a.responsible_team_id,
    CASE WHEN a.price_basis = 'piece' THEN tp.price ELSE a.rep_price END AS price,
    CASE WHEN a.price_basis = 'piece' THEN 1 ELSE a.measure_value END AS measure_value,
    CASE
        WHEN a.is_rework AND (a.chargeability IS NULL OR a.chargeability <> 'chargeable') THEN 0
        WHEN a.any_missing_price THEN NULL
        WHEN a.any_missing_team THEN NULL
        WHEN a.price_basis = 'weight' AND a.w_missing THEN NULL
        WHEN a.price_basis = 'length' AND a.len_missing THEN NULL
        WHEN a.price_basis = 'hour'   AND a.hr_missing THEN NULL
        WHEN a.price_basis = 'hole_count' AND a.hole_missing THEN NULL
        WHEN a.price_basis = 'piece' THEN 1 * tp.price
        ELSE a.measured_amount
    END AS amount,
    CASE
        WHEN a.is_rework AND a.chargeability = 'non_chargeable' THEN 'REWORK_NON_CHARGEABLE'
        WHEN a.is_rework AND (a.chargeability IS NULL OR a.chargeability <> 'chargeable') THEN 'REWORK_NO_BASIS'
        WHEN a.any_missing_price THEN 'MISSING_PRICE'
        WHEN a.any_missing_team THEN 'MISSING_TEAM'
        WHEN a.price_basis = 'weight' AND a.w_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'weight' AND a.w_fallback THEN 'MEASURE_FALLBACK'
        WHEN a.price_basis = 'length' AND a.len_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'hour'   AND a.hr_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'hole_count' AND a.hole_missing THEN 'MISSING_MEASURE'
        ELSE 'PRECISE'
    END AS anomaly_status
FROM agg a
LEFT JOIN task_piece_price tp ON tp.task_id = a.task_id;

CREATE VIEW eng.v_project_production_cost AS
SELECT
    main_project_id,
    subproject_id,
    project_operation_id,
    execute_team_id,
    date_trunc('month', occurred_at) AS month,
    COUNT(*) FILTER (WHERE NOT is_rework) AS normal_count,
    COUNT(*) FILTER (WHERE is_rework)     AS rework_count,
    SUM(amount) FILTER (WHERE NOT is_rework) AS normal_cost,
    SUM(amount) FILTER (WHERE is_rework)     AS rework_cost,
    SUM(amount) AS total_cost
FROM eng.v_operation_cost_trial
GROUP BY main_project_id, subproject_id, project_operation_id, execute_team_id,
         date_trunc('month', occurred_at);
"""


NEW_VIEWS_SQL = r"""
DROP VIEW IF EXISTS eng.v_project_production_cost;
DROP VIEW IF EXISTS eng.v_operation_cost_trial;

CREATE VIEW eng.v_operation_cost_trial AS
WITH report_facts AS (
    SELECT
        pr.task_id,
        pr.occurred_at,
        pt.attempt,
        (pt.attempt > 1 OR pt.rework_of_task_id IS NOT NULL) AS is_rework,
        pt.execute_team_id,
        ac.id             AS actual_component_id,
        ac.component_no,
        ac.actual_weight,
        sp.main_project_id,
        sp.id             AS subproject_id,
        rts.id            AS route_template_step_id,
        rts.operation_type_id,
        rts.project_operation_id AS rts_po_id,
        ro.responsible_team_id AS responsible_team_id,
        ro.chargeability  AS stored_chargeability,
        -- 有效计价资格：基于"明确责任判定（责任班组 vs 执行班组）"推导，不再依赖异常分类
        CASE
            WHEN (pt.attempt > 1 OR pt.rework_of_task_id IS NOT NULL) = FALSE THEN 'chargeable'
            WHEN ro.responsible_team_id IS NOT NULL AND ro.responsible_team_id = pt.execute_team_id THEN 'non_chargeable'
            WHEN ro.responsible_team_id IS NOT NULL AND ro.responsible_team_id <> pt.execute_team_id THEN 'chargeable'
            WHEN ro.responsible_team_id IS NULL AND ro.chargeability = 'chargeable' THEN 'chargeable'
            ELSE 'non_chargeable'
        END AS effective_chargeability,
        CASE
            WHEN (pt.attempt > 1 OR pt.rework_of_task_id IS NOT NULL) = FALSE THEN 'NORMAL_TASK'
            WHEN ro.responsible_team_id IS NOT NULL AND ro.responsible_team_id = pt.execute_team_id THEN 'SELF_RESPONSIBLE'
            WHEN ro.responsible_team_id IS NOT NULL AND ro.responsible_team_id <> pt.execute_team_id THEN 'OTHER_TEAM_RESPONSIBLE'
            WHEN ro.responsible_team_id IS NULL AND ro.chargeability = 'chargeable' THEN 'EXTERNAL'
            ELSE 'NO_BASIS_PENDING'
        END AS pricing_basis,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'weight' THEN pm.value END), 0) AS w_val,
        COALESCE(SUM(CASE WHEN pm.measure_type IN ('cut_length','weld_length','mach_length') THEN pm.value END), 0) AS len_val,
        COALESCE(SUM(rw.work_hours), 0) AS hr_worker,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'hours' THEN pm.value END), 0) AS hr_val,
        COALESCE(SUM(CASE WHEN pm.measure_type = 'hole_count' THEN pm.value END), 0) AS hole_val,
        CASE WHEN COUNT(CASE WHEN pm.measure_type = 'weight' THEN 1 END) > 0 THEN 1 ELSE 0 END AS has_w
    FROM prod.production_report pr
    JOIN prod.production_task pt      ON pt.id = pr.task_id
    JOIN eng.route_template_step rts  ON rts.id = pt.route_template_step_id
    JOIN prod.actual_component ac     ON ac.id = pt.actual_component_id
    JOIN md.subproject sp             ON sp.id = ac.subproject_id
    LEFT JOIN prod.production_measure pm ON pm.report_id = pr.id
    LEFT JOIN prod.production_report_worker rw ON rw.report_id = pr.id
    LEFT JOIN prod.rework_order ro    ON ro.id = pt.rework_order_id
    GROUP BY pr.id, pr.task_id, pr.occurred_at, pt.attempt, pt.rework_of_task_id, pt.execute_team_id,
             ac.id, ac.component_no, ac.actual_weight, sp.main_project_id, sp.id,
             rts.id, rts.operation_type_id, rts.project_operation_id,
             ro.responsible_team_id, ro.chargeability
),
po_resolved AS (
    SELECT rf.*, po.id AS project_operation_id, po.custom_name
    FROM report_facts rf
    LEFT JOIN LATERAL (
        SELECT po2.id, po2.custom_name
        FROM eng.project_operation po2
        WHERE po2.is_active
          AND ((rf.rts_po_id IS NOT NULL AND po2.id = rf.rts_po_id)
            OR (rf.rts_po_id IS NULL AND po2.operation_type_id = rf.operation_type_id
                AND (po2.main_project_id = rf.main_project_id OR po2.subproject_id = rf.subproject_id)))
        ORDER BY po2.id
        LIMIT 1
    ) po ON true
),
priced AS (
    SELECT r.*,
           MAX(r.occurred_at) OVER (PARTITION BY r.task_id) AS task_max_occurred_at,
           pop.price_basis,
           pop.price
    FROM po_resolved r
    LEFT JOIN LATERAL (
        SELECT x.price_basis, x.price
        FROM eng.project_operation_price x
        WHERE x.project_operation_id = r.project_operation_id
          AND x.effective_from <= r.occurred_at::date
          AND (x.effective_to IS NULL OR r.occurred_at::date < x.effective_to)
        ORDER BY x.effective_from DESC
        LIMIT 1
    ) pop ON true
),
task_piece_price AS (
    SELECT DISTINCT p.task_id, popp.price_basis, popp.price
    FROM priced p
    LEFT JOIN LATERAL (
        SELECT x.price_basis, x.price
        FROM eng.project_operation_price x
        WHERE x.project_operation_id = p.project_operation_id
          AND x.effective_from <= p.task_max_occurred_at::date
          AND (x.effective_to IS NULL OR p.task_max_occurred_at::date < x.effective_to)
        ORDER BY x.effective_from DESC
        LIMIT 1
    ) popp ON true
),
agg AS (
    SELECT
        task_id, actual_component_id, component_no, main_project_id, subproject_id,
        project_operation_id, operation_type_id, custom_name, execute_team_id,
        attempt, is_rework, price_basis,
        effective_chargeability, pricing_basis, responsible_team_id, stored_chargeability,
        MAX(occurred_at) AS occurred_at,
        SUM(CASE WHEN price_basis='weight' THEN CASE WHEN has_w=1 THEN w_val ELSE actual_weight END
                 WHEN price_basis='length' THEN len_val
                 WHEN price_basis='hour'   THEN COALESCE(hr_worker, hr_val)
                 WHEN price_basis='hole_count' THEN hole_val
                 ELSE 0 END) AS measure_value,
        SUM(CASE WHEN price IS NULL THEN 0 ELSE
              (CASE WHEN price_basis='weight' THEN CASE WHEN has_w=1 THEN w_val ELSE actual_weight END
                    WHEN price_basis='length' THEN len_val
                    WHEN price_basis='hour'   THEN COALESCE(hr_worker, hr_val)
                    WHEN price_basis='hole_count' THEN hole_val
                    ELSE 0 END) * price END) AS measured_amount,
        BOOL_OR(price IS NULL OR project_operation_id IS NULL) AS any_missing_price,
        BOOL_OR(execute_team_id IS NULL) AS any_missing_team,
        BOOL_OR(price_basis='weight' AND has_w=0 AND actual_weight IS NULL) AS w_missing,
        BOOL_OR(price_basis='weight' AND has_w=0 AND actual_weight IS NOT NULL) AS w_fallback,
        BOOL_OR(price_basis='length' AND len_val=0) AS len_missing,
        BOOL_OR(price_basis='hour' AND hr_worker=0 AND hr_val=0) AS hr_missing,
        BOOL_OR(price_basis='hole_count' AND hole_val=0) AS hole_missing,
        MAX(price) AS rep_price
    FROM priced
    GROUP BY task_id, actual_component_id, component_no, main_project_id, subproject_id,
             project_operation_id, operation_type_id, custom_name, execute_team_id,
             attempt, is_rework, price_basis,
             effective_chargeability, pricing_basis, responsible_team_id, stored_chargeability
)
SELECT
    a.task_id,
    a.actual_component_id,
    a.component_no,
    a.main_project_id,
    a.subproject_id,
    a.project_operation_id,
    a.operation_type_id,
    a.custom_name,
    a.execute_team_id,
    a.occurred_at,
    a.attempt,
    a.is_rework,
    a.price_basis,
    a.effective_chargeability,
    a.stored_chargeability,
    a.responsible_team_id,
    a.pricing_basis,
    CASE WHEN a.price_basis = 'piece' THEN tp.price ELSE a.rep_price END AS price,
    CASE WHEN a.price_basis = 'piece' THEN 1 ELSE a.measure_value END AS measure_value,
    CASE
        WHEN a.is_rework AND a.effective_chargeability <> 'chargeable' THEN 0
        WHEN a.any_missing_price THEN NULL
        WHEN a.any_missing_team THEN NULL
        WHEN a.price_basis = 'weight' AND a.w_missing THEN NULL
        WHEN a.price_basis = 'length' AND a.len_missing THEN NULL
        WHEN a.price_basis = 'hour'   AND a.hr_missing THEN NULL
        WHEN a.price_basis = 'hole_count' AND a.hole_missing THEN NULL
        WHEN a.price_basis = 'piece' THEN 1 * tp.price
        ELSE a.measured_amount
    END AS amount,
    CASE
        WHEN a.is_rework AND a.effective_chargeability <> 'chargeable' AND a.pricing_basis = 'SELF_RESPONSIBLE' THEN 'REWORK_SELF_RESPONSIBLE'
        WHEN a.is_rework AND a.effective_chargeability <> 'chargeable' THEN 'REWORK_NO_BASIS'
        WHEN a.is_rework AND a.effective_chargeability = 'chargeable' AND a.pricing_basis = 'OTHER_TEAM_RESPONSIBLE' THEN 'REWORK_OTHER_RESPONSIBLE'
        WHEN a.is_rework AND a.effective_chargeability = 'chargeable' AND a.pricing_basis = 'EXTERNAL' THEN 'REWORK_EXTERNAL'
        WHEN a.any_missing_price THEN 'MISSING_PRICE'
        WHEN a.any_missing_team THEN 'MISSING_TEAM'
        WHEN a.price_basis = 'weight' AND a.w_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'weight' AND a.w_fallback THEN 'MEASURE_FALLBACK'
        WHEN a.price_basis = 'length' AND a.len_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'hour'   AND a.hr_missing THEN 'MISSING_MEASURE'
        WHEN a.price_basis = 'hole_count' AND a.hole_missing THEN 'MISSING_MEASURE'
        ELSE 'PRECISE'
    END AS anomaly_status
FROM agg a
LEFT JOIN task_piece_price tp ON tp.task_id = a.task_id;

CREATE VIEW eng.v_project_production_cost AS
SELECT
    main_project_id,
    subproject_id,
    project_operation_id,
    execute_team_id,
    date_trunc('month', occurred_at) AS month,
    COUNT(*) FILTER (WHERE NOT is_rework) AS normal_count,
    COUNT(*) FILTER (WHERE is_rework)     AS rework_count,
    SUM(amount) FILTER (WHERE NOT is_rework) AS normal_cost,
    SUM(amount) FILTER (WHERE is_rework)     AS rework_cost,
    SUM(amount) AS total_cost
FROM eng.v_operation_cost_trial
GROUP BY main_project_id, subproject_id, project_operation_id, execute_team_id,
         date_trunc('month', occurred_at);
"""


def upgrade() -> None:
    op.execute(NEW_VIEWS_SQL)


def downgrade() -> None:
    op.execute(C3_VIEWS_SQL)
