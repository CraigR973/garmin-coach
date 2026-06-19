"""Shared slowapi rate limiter and per-request key helpers."""

import hashlib
import json

import jwt
import structlog
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Counters are in-process and reset on restart. This is acceptable for a
# single-instance Railway deployment — the DB lockout (max_attempts) is the
# durable brute-force guard; these counters add a short-term rate layer.
limiter = Limiter(key_func=get_remote_address)


def per_player_key(request: Request) -> str:
    """Rate-limit key derived from the bearer token's player_id.

    Falls back to remote address when no valid token is present so
    unauthenticated requests are still bounded (by IP).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            payload = jwt.decode(
                token,
                settings.jwt_access_secret,
                algorithms=["HS256"],
                # Allow expired tokens so the player is still rate-limited
                # by ID rather than falling through to the shared IP bucket.
                options={"verify_exp": False},
            )
            return f"player:{payload['sub']}"
        except Exception:
            pass
    return get_remote_address(request)


def login_key(request: Request) -> str:
    """Key for login: email + IP to limit per-credential brute-force.

    FastAPI reads and caches the request body in request._body before calling
    the route handler, so accessing it synchronously here is safe.
    """
    try:
        body_bytes: bytes = getattr(request, "_body", b"") or b""
        data = json.loads(body_bytes)
        email = str(data.get("email", "")).lower()
    except Exception:
        email = ""
    return f"login:{email}:{get_remote_address(request)}"


def refresh_token_key(request: Request) -> str:
    """Key for token refresh: SHA-256 of the refresh token so each token has its own bucket.

    FastAPI reads and caches the request body in request._body before calling
    the route handler, so accessing it synchronously here is safe.
    """
    try:
        body_bytes: bytes = getattr(request, "_body", b"") or b""
        data = json.loads(body_bytes)
        raw_token = str(data.get("refresh_token", ""))
        return f"refresh:{hashlib.sha256(raw_token.encode()).hexdigest()}"
    except Exception:
        return get_remote_address(request)
