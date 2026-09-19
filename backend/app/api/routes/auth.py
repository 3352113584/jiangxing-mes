"""Phase 4 Sprint 1 — 认证路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.auth import CurrentUserOut, LoginRequest, TokenResponse
from app.services.auth_service import authenticate, build_token_response
from app.services.errors import BusinessError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate(db, req.username, req.password)
    if user is None:
        raise BusinessError("AUTH_FAILED", "用户名或密码错误", 401)
    return build_token_response(db, user)


@router.get("/me", response_model=CurrentUserOut)
def me(ctx=Depends(get_current_user)):
    return CurrentUserOut(
        user_id=ctx.user_id,
        username=ctx.username,
        employee_id=ctx.employee_id,
        primary_team_id=ctx.primary_team_id,
        primary_team_name=ctx.primary_team_name,
        roles=ctx.roles,
    )
