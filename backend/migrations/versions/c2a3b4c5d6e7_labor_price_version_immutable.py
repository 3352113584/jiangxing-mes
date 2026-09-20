"""劳务验收整改 c2：labor_pricing_rule_version 历史不可变守卫（ORANGE-1）。

规则：
  * 已生效版本（effective_from <= CURRENT_DATE）禁止 DELETE；
  * 已生效版本禁止修改 immutable 字段（rule_id / version_no / unit_price /
    effective_from / approved_by）；仅允许"安全关闭"（设置 effective_to / 切换
    is_current 指针），不改价格与生效起始；
  * 未来版本（effective_from > CURRENT_DATE）可自由 UPDATE / DELETE；
  * 历史价格按 effective 区间解析，新价必须新增版本（服务层按 occurred_at 时间旅行匹配）。
说明：本触发器只作用于 eng.labor_pricing_rule_version，不影响 f0 的 T-17
（project_operation_price 守卫），二者职责分离。

Revision ID: c2a3b4c5d6e7
Revises: c1a2b3c4d5e6
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPGRADE_SQL = r"""
-- ============================================================
-- ORANGE-1：labor_pricing_rule_version 历史不可变守卫
-- ============================================================
CREATE OR REPLACE FUNCTION mes_labor_price_version_guard() RETURNS trigger AS $$
BEGIN
    -- DELETE：已生效版本禁止删除（历史不可抹除）
    IF TG_OP = 'DELETE' THEN
        IF OLD.effective_from <= CURRENT_DATE THEN
            RAISE EXCEPTION 'labor_pricing_rule_version 已生效版本(effective_from=%)禁止删除', OLD.effective_from;
        END IF;
        RETURN OLD;
    END IF;

    -- INSERT：自由（含新增版本、未来版本）；is_current 唯一性由 ix_lprv_current 约束保障
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    -- UPDATE：仅对"已生效"版本施加 immutable 约束
    IF NEW.effective_from <= CURRENT_DATE THEN
        IF NEW.rule_id IS DISTINCT FROM OLD.rule_id
           OR NEW.version_no IS DISTINCT FROM OLD.version_no
           OR NEW.unit_price IS DISTINCT FROM OLD.unit_price
           OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
           OR NEW.approved_by IS DISTINCT FROM OLD.approved_by THEN
            RAISE EXCEPTION 'labor_pricing_rule_version 已生效版本禁止修改价格/版本/生效起始/归属（历史结果不可变；改价请新增版本）';
        END IF;
        -- 允许：effective_to / is_current 的调整（安全关闭 / 当前指针切换）
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_labor_price_version_guard
    BEFORE INSERT OR UPDATE OR DELETE ON eng.labor_pricing_rule_version
    FOR EACH ROW EXECUTE FUNCTION mes_labor_price_version_guard();
"""


DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trg_labor_price_version_guard ON eng.labor_pricing_rule_version;
DROP FUNCTION IF EXISTS mes_labor_price_version_guard();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
