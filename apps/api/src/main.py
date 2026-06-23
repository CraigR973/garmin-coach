from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.types import Event, Hint
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.config import Environment, docs_urls, settings
from src.logging_config import configure_logging
from src.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from src.rate_limit import limiter
from src.routers import (
    auth,
    block_generator,
    coaching_state,
    daily_loop,
    experiments,
    health,
    holiday,
    insights,
    me,
    notifications,
    restructure,
    strength_brief,
    workout_delivery,
)
from src.scheduler import create_scheduler

configure_logging(settings.log_level)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _scrub_pii(event: Event, hint: Hint) -> Event | None:
    """Remove display names from Sentry events so player names never appear in error reports."""
    user: Any = event.get("user")
    if isinstance(user, dict):
        user.pop("display_name", None)
        user.pop("username", None)
    return event


if settings.sentry_dsn_backend:
    sentry_sdk.init(
        dsn=settings.sentry_dsn_backend,
        environment=settings.environment,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        send_default_pii=False,
        before_send=_scrub_pii,
        traces_sample_rate=0.0 if settings.environment != Environment.production else 0.05,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("api starting", environment=settings.environment)
    scheduler = create_scheduler()
    app.state.scheduler = scheduler
    if settings.scheduler_enabled:
        scheduler.start()
        log.info("scheduler started")
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("scheduler stopped")


# Docs/OpenAPI are disabled in production (private app — don't expose the schema
# anonymously); kept in dev/staging. (Review finding P3-7.)
_docs = docs_urls(settings.environment)
app = FastAPI(
    title="Garmin Coach API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=_docs["docs_url"],
    redoc_url=_docs["redoc_url"],
    openapi_url=_docs["openapi_url"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(notifications.router)
app.include_router(coaching_state.router)
app.include_router(daily_loop.router)
app.include_router(workout_delivery.router)
app.include_router(restructure.router)
app.include_router(holiday.router)
app.include_router(block_generator.router)
app.include_router(insights.router)
app.include_router(experiments.router)
app.include_router(strength_brief.router)
