"""Phase 4 Sprint 1 — 认证相关 Schema。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user_id: int
    username: str
    employee_id: int | None = None
    primary_team_id: int | None = None
    primary_team_name: str | None = None
    roles: list[str] = []


class CurrentUserOut(BaseModel):
    user_id: int
    username: str
    employee_id: int | None = None
    primary_team_id: int | None = None
    primary_team_name: str | None = None
    roles: list[str] = []
