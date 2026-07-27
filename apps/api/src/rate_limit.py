"""Shared slowapi rate limiter and per-request key helpers."""

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# Counters are in-process and reset on restart. Device credentials have 256 bits
# of entropy, so these limits bound expensive actions rather than defending a
# small credential space.
limiter = Limiter(key_func=get_remote_address)


def per_user_key(request: Request) -> str:
    """Rate-limit key derived from a one-way fingerprint of the bearer token.

    Auth resolution stores the verified profile id on request state before the
    endpoint wrapper runs, so all of one user's devices share a bucket. Hashing
    the bearer remains the fail-closed fallback for callers/dependency overrides
    that do not populate state; the raw credential never enters limiter storage.
    """
    user_id = getattr(request.state, "current_user_id", None)
    if isinstance(user_id, str) and user_id:
        return f"user:{user_id}"
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return f"device:{hashlib.sha256(token.encode()).hexdigest()}"
    return get_remote_address(request)


# One shared authenticated budget across every user-triggered paid-generation
# route, so a stolen device token cannot multiply its allowance by switching
# endpoints. Piper has a separate, more generous request-rate budget but still
# has a single CPU slot in ``services.workload_budget``.
paid_generation_limit = limiter.shared_limit(
    "30/hour",
    scope="paid-generation",
    key_func=per_user_key,
)
tts_synthesis_limit = limiter.shared_limit(
    "60/hour",
    scope="tts-synthesis",
    key_func=per_user_key,
)
