"""Phase 4 Sprint 1 — 业务异常。

服务层抛出 BusinessError，路由层捕获并映射为结构化 JSON 错误响应。
code 为稳定业务码（前端/Android 可据此分支，如幂等识别、权限拒绝）。
"""
from __future__ import annotations


class BusinessError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        extra: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra
