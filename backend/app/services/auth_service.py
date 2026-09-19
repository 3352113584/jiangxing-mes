"""Phase 4 Sprint 1 — 认证与当前用户上下文。

Token 为无状态 HMAC 签名；用户→班组链路：
user_account.employee_id → team_membership(primary, current) → team。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_token, verify_password
from app.db.models.md import (
    Employee,
    Role,
    Team,
    TeamMembership,
    UserAccount,
    UserRole,
)


@dataclass
class UserContext:
    user_id: int
    username: str
    employee_id: Optional[int]
    primary_team_id: Optional[int]
    primary_team_name: Optional[str]
    roles: list[str]


def authenticate(db: Session, username: str, password: str) -> Optional[UserAccount]:
    user = db.execute(
        select(UserAccount).where(UserAccount.username == username)
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def get_user_context(db: Session, user_id: int) -> Optional[UserContext]:
    user = db.get(UserAccount, user_id)
    if user is None:
        return None
    employee_id = user.employee_id
    primary_team_id = None
    primary_team_name = None
    if employee_id is not None:
        row = db.execute(
            select(Team.id, Team.name)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                TeamMembership.employee_id == employee_id,
                TeamMembership.membership_kind == "primary",
                TeamMembership.is_current.is_(True),
            )
        ).first()
        if row is not None:
            primary_team_id, primary_team_name = row
    roles = db.execute(
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).scalars().all()
    return UserContext(
        user_id=user.id,
        username=user.username,
        employee_id=employee_id,
        primary_team_id=primary_team_id,
        primary_team_name=primary_team_name,
        roles=list(roles),
    )


def build_token_response(db: Session, user: UserAccount):
    from app.schemas.auth import TokenResponse

    ctx = get_user_context(db, user.id)
    return TokenResponse(
        access_token=create_token(user.id),
        user_id=user.id,
        username=user.username,
        employee_id=ctx.employee_id if ctx else None,
        primary_team_id=ctx.primary_team_id if ctx else None,
        primary_team_name=ctx.primary_team_name if ctx else None,
        roles=ctx.roles if ctx else [],
    )
