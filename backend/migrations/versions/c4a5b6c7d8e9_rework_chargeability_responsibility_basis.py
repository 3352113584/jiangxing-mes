"""劳务验收整改 c4：撤销 parent_category→chargeability 硬编码映射（RED-A），并堵住 NULL 绕过（ORANGE-B）。

第 3 轮独立实仓验收结论：上一轮 c1 触发器把 ref.reason_dictionary.parent_category（异常分类）
直接当成劳务责任规则推导 chargeability，这是未经业务确认的映射，违反冻结纪律。

本轮（最小整改，不修改历史迁移 c1/c2/c3、不修改 operation_type）：
1. 替换 trg_rework_order_chargeability_guard：
   - 不再引用 parent_category；chargeability 必须由业务基于"明确责任判定结果"显式给出。
   - chargeability=NULL 时默认置 'pending'（待责任确认 / 不可结算），杜绝"以 NULL 绕过责任/计价规则"。
2. 扩展 ck_rework_order_chargeability_values，允许 'pending'（合法的第三态：待确认）。

注意：本迁移只修正 c1 引入的错误映射，不触动 c1 新增的 responsible_team_id 列/FK（那是 ORANGE-2 的可追溯载体，保留）。

Revision ID: c4a5b6c7d8e9
Revises: c3a4b5c6d7e8
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'c3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 旧触发器（c1 引入的错误 parent_category→chargeability 映射）重建 SQL，供 DOWNGRADE 还原。
OLD_TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION mes_rework_order_chargeability_guard() RETURNS trigger AS $$
DECLARE
    v_parent   text;
    v_expected text;
BEGIN
    SELECT parent_category INTO v_parent
      FROM ref.reason_dictionary WHERE id = NEW.reason_category_id;
    IF v_parent IS NULL THEN
        RETURN NEW;
    END IF;
    IF v_parent = 'quality' THEN
        v_expected := 'non_chargeable';
    ELSE
        v_expected := 'chargeable';
    END IF;
    IF NEW.chargeability IS NULL THEN
        NEW.chargeability := v_expected;
        RETURN NEW;
    END IF;
    IF NEW.chargeability IN ('chargeable', 'non_chargeable')
       AND NEW.chargeability <> v_expected THEN
        RAISE EXCEPTION 'rework_order 责任与计价矛盾: reason parent=% 应为%, 实际=%',
            v_parent, v_expected, NEW.chargeability;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_rework_order_chargeability_guard
    BEFORE INSERT OR UPDATE ON prod.rework_order
    FOR EACH ROW EXECUTE FUNCTION mes_rework_order_chargeability_guard();
"""


UPGRADE_SQL = r"""
-- ============================================================
-- RED-A / ORANGE-B：撤销 parent_category→chargeability 硬编码
-- ============================================================
-- 1) 删除旧触发器与函数（其错误地将异常分类映射为计价资格）
DROP TRIGGER IF EXISTS trg_rework_order_chargeability_guard ON prod.rework_order;
DROP FUNCTION IF EXISTS mes_rework_order_chargeability_guard();

-- 2) 新建守卫：不再引用 parent_category；
--    chargeability 必须由业务基于"明确责任判定结果（责任班组 vs 执行班组）"显式给出。
--    chargeability=NULL → 默认 'pending'（待责任确认 / 不可结算），堵住 ORANGE-B 绕过。
CREATE OR REPLACE FUNCTION mes_rework_order_chargeability_guard() RETURNS trigger AS $$
BEGIN
    -- RED-A：不再基于 ref.reason_dictionary.parent_category（异常分类）推导 chargeability。
    -- ORANGE-B：不允许以 NULL 绕过责任/计价规则；无明确依据进入"待责任确认/不可结算"。
    IF NEW.chargeability IS NULL THEN
        NEW.chargeability := 'pending';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_rework_order_chargeability_guard
    BEFORE INSERT OR UPDATE ON prod.rework_order
    FOR EACH ROW EXECUTE FUNCTION mes_rework_order_chargeability_guard();

-- 3) 扩展取值约束，纳入 'pending'（待责任确认 / 不可结算）
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_chargeability_values;
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_chargeability_values
    CHECK (chargeability IN ('chargeable', 'non_chargeable', 'pending'));
"""


DOWNGRADE_SQL = r"""
-- 还原 c3 状态：恢复 c1 旧触发器（parent_category 映射）与两值约束。
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_chargeability_values;
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_chargeability_values
    CHECK (chargeability IN ('chargeable', 'non_chargeable'));

DROP TRIGGER IF EXISTS trg_rework_order_chargeability_guard ON prod.rework_order;
DROP FUNCTION IF EXISTS mes_rework_order_chargeability_guard();

""" + OLD_TRIGGER_SQL


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
