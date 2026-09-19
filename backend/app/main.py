"""Phase 4 Sprint 1 — FastAPI 应用入口。

仅承载 Sprint 1 业务闭环：PC 生产任务分配、Android 构件登记、PC 生产履历。
不依赖框架级默认值覆盖契约服务层校验（幂等/并发/状态机均在 service 显式实现，可审计）。
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import android, auth, history, tasks
from app.services.errors import BusinessError


def _resolve_cors_origins() -> list[str]:
    """解析允许的前端 Origin。

    - 生产：必须显式配置 MES_CORS_ORIGINS（逗号分隔），禁止使用 *。
    - 未配置且非开发模式：默认拒绝所有跨域（空列表）。
    - 仅开发模式（MES_DEBUG=true）允许通配 *，方便本机调试。
    """
    raw = os.getenv("MES_CORS_ORIGINS", "").strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if origins:
        return origins
    if os.getenv("MES_DEBUG", "false").lower() in ("1", "true", "yes"):
        return ["*"]
    return []


CORS_ORIGINS = _resolve_cors_origins()
# 仅当明确配置了具体 Origin 时才允许携带凭据；
# 通配(*)或拒绝列表不允许 credentials（避免非法 CORS 组合）。
ALLOW_CREDENTIALS = bool(CORS_ORIGINS) and "*" not in CORS_ORIGINS

app = FastAPI(title="匠星智造 MES — Phase 4 Sprint 1", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(
        status_code=exc.status,
        content={"ok": False, "code": exc.code, "message": exc.message, "extra": exc.extra},
    )


@app.get("/health")
def health():
    return {"status": "ok", "sprint": "phase4-sprint1"}


app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(android.router)
app.include_router(history.router)
