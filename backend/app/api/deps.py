"""Phase 4 Sprint 1 — API 依赖：当前登录用户解析。"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.services.auth_service import UserContext, get_user_context


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> UserContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或令牌缺失")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    ctx = get_user_context(db, payload["sub"])
    if ctx is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return ctx
