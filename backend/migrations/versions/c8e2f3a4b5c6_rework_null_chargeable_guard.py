"""R6 ORANGE-3：补齐 NULL/PENDING 与 chargeable 的数据库一致性约束。

背景：
- R4/R5 已冻结 `responsibility_kind = NULL ≡ PENDING`，且二者均不得产生正式劳务计价
  （最终计价只认 `effective_chargeability`，由视图/服务推导）。
- R4 迁移 `c6a7b8c9d0e1`（responsibility_kind）已用 `ck_rework_order_pending_chargeable`
  拒绝 `PENDING + chargeability='chargeable'`；但数据库层**未显式拒绝**
  `NULL + chargeability='chargeable'`，造成 NULL 与 PENDING 在 DB 层不一致（R6 ORANGE-3）。

本迁移补齐该缺口：新增 CHECK `ck_rework_order_null_chargeable`，
使 `NULL` 与 `PENDING` 在数据库层得到一致的拒绝。

约束范围：仅新增一个 CHECK 约束，**不修改任何历史迁移（c1~c7）**，不改动表结构、
不改动 View/Service、不引入人工审批覆盖路径。
"""
from alembic import op

revision = 'c8e2f3a4b5c6'
down_revision = 'c7b8c9d0e1f2'
branch_labels = None
depends_on = None

ADD_CK = (
    "ALTER TABLE prod.rework_order "
    "ADD CONSTRAINT ck_rework_order_null_chargeable "
    "CHECK (NOT (responsibility_kind IS NULL AND chargeability = 'chargeable'))"
)
DROP_CK = (
    "ALTER TABLE prod.rework_order "
    "DROP CONSTRAINT IF EXISTS ck_rework_order_null_chargeable"
)


def upgrade():
    op.execute(ADD_CK)


def downgrade():
    op.execute(DROP_CK)
