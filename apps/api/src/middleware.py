import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.config import Environment, settings
from src.services.egress_budget import response_byte_counter


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request, propagate it in the response header,
    and bind it to structlog context so every log line emitted during the request carries it."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class EgressBudgetMiddleware(BaseHTTPMiddleware):
    """Feed served response bytes into the egress-budget proxy (Batch 204, DS190-07).

    Uses ``Content-Length`` only — every response this API returns is a
    buffered JSON body with that header set, so a missing header (which
    would under-count a streaming response, of which this API has none)
    is intentionally skipped rather than guessed at.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                response_byte_counter.add(int(content_length))
            except ValueError:
                pass
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        if settings.environment != Environment.development:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Mitigate XSS-based exfiltration of the long-lived localStorage refresh
        # token. The frontend is a single-page app served from Vercel; this API
        # only serves JSON so there is no script/style/img surface here.
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
