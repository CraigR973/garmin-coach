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

    Opaque device tokens carry no user claim. Hashing keeps the raw credential
    out of limiter state and logs while still giving each device its own bucket.
    Requests without a bearer credential fall back to their remote address.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return f"device:{hashlib.sha256(token.encode()).hexdigest()}"
    return get_remote_address(request)
