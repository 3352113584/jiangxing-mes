"""Phase 4 Sprint 1 — 通用 Schema。"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封（成功）。"""

    ok: bool = True
    data: T
    message: Optional[str] = None


class ErrorDetail(BaseModel):
    """统一错误结构。"""

    ok: bool = False
    code: str
    message: str
    # 业务附带信息（如已存在记录的 id），便于客户端幂等处理。
    extra: Optional[dict] = None
