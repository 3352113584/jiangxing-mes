"""Phase 4 Sprint 1 — 无外部依赖的密码哈希与 Token 工具。

- 密码：PBKDF2-HMAC-SHA256（stdlib），存储格式 pbkdf2_sha256$iterations$salt$hex。
- Token：HMAC-SHA256 签名的 JSON payload（stdlib），格式 <b64payload>.<hexsig>。
  不引入 pyjwt/itsdangerous，保持依赖最小、可审计。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from app.core.config import settings

_PBKDF2_ITER = 100_000
_ALGO = "sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_token(user_id: int, ttl_seconds: Optional[int] = None) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else settings.TOKEN_TTL
    payload = json.dumps({"sub": user_id, "exp": int(time.time()) + ttl}).encode("utf-8")
    p = _b64encode(payload)
    sig = hmac.new(settings.SECRET.encode("utf-8"), p.encode("utf-8"), _ALGO).hexdigest()
    return f"{p}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    try:
        p, sig = token.rsplit(".", 1)
        expected = hmac.new(settings.SECRET.encode("utf-8"), p.encode("utf-8"), _ALGO).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(_b64decode(p))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
