"""一次性管理员初始化（运维脚本，不在应用运行态调用）。

用法（在已部署环境，且 deploy/.env 已提供数据库变量）：
  export MES_DATABASE_URL=postgresql+psycopg://mes_app:***@postgres:5432/jiangxing_mes
  export MES_INIT_ADMIN_USER=admin
  export MES_INIT_ADMIN_PASSWORD='<强密码，从密钥管理获取>'
  python deploy/scripts/init_admin.py

设计原则：
- 不硬编码任何密码；全部来自环境变量。
- 幂等：用户名已存在则更新密码；角色未关联则关联 SUPER_ADMIN。
- 仅创建/更新 user_account 与 user_role，不触碰任何业务规则。
- 直接操作数据库，生产操作前请做好备份。

注意：本脚本不会在容器启动时自动运行；由运维在首次部署后手动执行一次。
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker

# 让脚本可直接 import 后端模块（backend/ 在仓库根下）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  (register models)
from app.db.models.md import Role, UserAccount, UserRole  # noqa: E402


def main() -> int:
    db_url = os.environ.get("MES_DATABASE_URL")
    if not db_url:
        print("ERROR: MES_DATABASE_URL 未设置", file=sys.stderr)
        return 2

    username = os.environ.get("MES_INIT_ADMIN_USER")
    password = os.environ.get("MES_INIT_ADMIN_PASSWORD")
    if not username or not password:
        print(
            "ERROR: MES_INIT_ADMIN_USER / MES_INIT_ADMIN_PASSWORD 必须设置",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(db_url, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as db:
        user = db.execute(
            select(UserAccount).where(UserAccount.username == username)
        ).scalar_one_or_none()
        if user is None:
            user = UserAccount(username=username, password_hash=hash_password(password))
            db.add(user)
            db.flush()
            print(f"created user_account: {username} (id={user.id})")
        else:
            user.password_hash = hash_password(password)
            print(f"updated password for user_account: {username} (id={user.id})")

        role = db.execute(
            select(Role).where(Role.role_code == "SUPER_ADMIN")
        ).scalar_one_or_none()
        if role is None:
            role = db.execute(
                select(Role).where(Role.role_code == "admin")
            ).scalar_one_or_none()
        if role is None:
            print(
                "ERROR: 未找到 SUPER_ADMIN/admin 角色（请先完成 migration 与角色 seed）",
                file=sys.stderr,
            )
            return 3

        exists = db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        ).scalar_one_or_none()
        if exists is None:
            db.execute(insert(UserRole).values(user_id=user.id, role_id=role.id))
            print(f"granted role {role.role_code} to {username}")
        else:
            print(f"role {role.role_code} already granted to {username}")

        db.commit()
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
