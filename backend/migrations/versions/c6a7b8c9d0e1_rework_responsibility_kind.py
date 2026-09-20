"""劳务验收整改 c6（第 4 轮）：新增 responsibility_kind 责任判定字段与 DB 层防旁路约束。

第 4 轮独立实仓验收要求：
- 把"返工为什么发生、谁负责、谁执行、是否计价"彻底分开。
- 不再通过 `responsible_team_id != execute_team_id` 猜测责任（那是事实关系，不是充分计价条件）。
- 引入显式责任判定结果 responsibility_kind：
    TEAM      : 明确某个班组承担责任（responsible_team_id 必须存在）
    NON_TEAM  : 明确责任不属于执行班组（图纸/材料/前道工序/客户变更等外部原因）
    PENDING   : 责任尚未确认，不得进入劳务结算
  NULL（未设置）= 无责任依据，按 PENDING 等价处理（不可结算）。

DB 层防旁路（§七）：
1. TEAM 必须指定 responsible_team_id（否则禁止）。
2. NON_TEAM 的 responsible_team_id 必须为 NULL（不得被误当作责任班组参与计算）。
3. PENDING 不得与 chargeability='chargeable' 共存（禁止进入计价）。
4. PENDING + chargeable=NULL 最终必须 pending / 不可结算（视图层处理）。

另：修复 ORM 漂移（§十一）——DB 的 chargeability 三值 CK（含 pending）与 ORM 两值不符；
此处显式再断言三值 CK，使 ORM / DB / Alembic metadata 三者一致（不修改历史 migration）。

视图逻辑不在此迁移，留待 c7 重写（视图非数据，可独立重写）。

Revision ID: c6a7b8c9d0e1
Revises: c5b6c7d8e9f0
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'c5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPGRADE_SQL = r"""
-- ============================================================
-- 第4轮：responsibility_kind 责任判定字段 + DB 层防旁路约束
-- ============================================================
ALTER TABLE prod.rework_order ADD COLUMN responsibility_kind varchar(16);

-- 取值约束：TEAM / NON_TEAM / PENDING 或 NULL（NULL=无依据→不可结算）
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_resp_kind_values
    CHECK (responsibility_kind IS NULL OR responsibility_kind IN ('TEAM', 'NON_TEAM', 'PENDING'));

-- 责任主体一致性：
--   TEAM     ⇒ responsible_team_id 必须非空（谁担责必须指明）
--   NON_TEAM ⇒ responsible_team_id 必须为 NULL（外部责任，无单一担责班组）
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_resp_team
    CHECK (
        (responsibility_kind <> 'TEAM'     OR responsible_team_id IS NOT NULL)
        AND (responsibility_kind <> 'NON_TEAM' OR responsible_team_id IS NULL)
    );

-- PENDING 不得进入计价：禁止 (PENDING + chargeability='chargeable') 共存
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_pending_chargeable
    CHECK (NOT (responsibility_kind = 'PENDING' AND chargeability = 'chargeable'));

-- 修复 ORM 漂移：chargeability 三值 CK（含 pending）显式再断言，
-- 使 ORM / DB / Alembic metadata 三者一致（DB 当前已是三值，此处可追溯化）。
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_chargeability_values;
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_chargeability_values
    CHECK (chargeability IN ('chargeable', 'non_chargeable', 'pending'));
"""


DOWNGRADE_SQL = r"""
-- 还原 c5 状态：移除 responsibility_kind 及其约束；chargeability 维持 c4 引入的三值（与 c5 前一致）。
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_resp_kind_values;
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_resp_team;
ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_pending_chargeable;
ALTER TABLE prod.rework_order
    DROP COLUMN IF EXISTS responsibility_kind;

ALTER TABLE prod.rework_order
    DROP CONSTRAINT IF EXISTS ck_rework_order_chargeability_values;
ALTER TABLE prod.rework_order
    ADD CONSTRAINT ck_rework_order_chargeability_values
    CHECK (chargeability IN ('chargeable', 'non_chargeable', 'pending'));
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
