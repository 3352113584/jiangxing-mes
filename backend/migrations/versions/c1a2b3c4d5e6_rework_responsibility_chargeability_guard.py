"""劳务验收整改 c1：返工责任主体可追溯 + reason/chargeability 一致性守卫。

- prod.rework_order 新增 responsible_team_id（责任班组，谁造成问题/承担责任），
  与执行返工班组（production_task.execute_team_id）区分，满足 ORANGE-2 可追溯要求。
- 新增 mes_rework_order_chargeability_guard 触发器（RED-2）：
  复用 ref.reason_dictionary.parent_category 判定责任归属，不新增类别：
    parent='quality'（quality_rework / quality_scrap）→ 班组责任 → non_chargeable
    其余（material / equipment / technical_drawing / production_organization / logistics / other）
      → 非班组责任 → chargeable
  规则：chargeability 为空时按原因派生；明确取值与原因矛盾时拒绝写入，防止矛盾状态进入计价。
  注：非法取值（'bogus' 等）交由 ck_rework_order_chargeability_values 拦截，本触发器只校验合法取值的一致性。

本迁移为线性链 beb27ec57bc8 → c1a2b3c4d5e6。不动历史迁移、不改 operation_type。

Revision ID: c1a2b3c4d5e6
Revises: beb27ec57bc8
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'beb27ec57bc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPGRADE_SQL = r"""
-- 返工责任主体可追溯：区分"责任班组（谁造成问题）"与"执行返工班组"
ALTER TABLE prod.rework_order
    ADD COLUMN responsible_team_id BIGINT;
ALTER TABLE prod.rework_order
    ADD CONSTRAINT fk_rework_order_responsible_team_id_team
    FOREIGN KEY (responsible_team_id) REFERENCES md.team(id) ON DELETE RESTRICT;

-- ============================================================
-- reason_category 与 chargeability 一致性守卫（RED-2）
-- 业务语义：复用 ref.reason_dictionary.parent_category，不新增类别
--   parent='quality'       → 班组责任 → non_chargeable
--   其余（material/equipment/technical_drawing/production_organization/logistics/other）
--                        → 非班组责任 → chargeable
-- 规则：chargeability 为空时按原因派生；明确取值与原因矛盾时拒绝写入。
-- 注：非法取值（'bogus' 等）由 ck_rework_order_chargeability_values 拦截。
-- ============================================================
CREATE OR REPLACE FUNCTION mes_rework_order_chargeability_guard() RETURNS trigger AS $$
DECLARE
    v_parent   text;
    v_expected text;
BEGIN
    SELECT parent_category INTO v_parent
      FROM ref.reason_dictionary WHERE id = NEW.reason_category_id;
    IF v_parent IS NULL THEN
        RETURN NEW;  -- 安全网：原因缺分类时不强行推导
    END IF;

    IF v_parent = 'quality' THEN
        v_expected := 'non_chargeable';
    ELSE
        v_expected := 'chargeable';
    END IF;

    IF NEW.chargeability IS NULL THEN
        NEW.chargeability := v_expected;  -- 按原因派生，避免空值进入计价
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


DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trg_rework_order_chargeability_guard ON prod.rework_order;
DROP FUNCTION IF EXISTS mes_rework_order_chargeability_guard();

ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS fk_rework_order_responsible_team_id_team;
ALTER TABLE prod.rework_order
    DROP COLUMN IF EXISTS responsible_team_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
