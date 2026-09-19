"""Phase 4 Sprint 1 — FastAPI 应用入口。

仅承载 Sprint 1 业务闭环：PC 生产任务分配、Android 构件登记、PC 生产履历。
不依赖框架级默认值覆盖契约服务层校验（幂等/并发/状态机均在 service 显式实现，可审计）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import android, auth, history, tasks
from app.services.errors import BusinessError

app = FastAPI(title="匠星智造 MES — Phase 4 Sprint 1", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
