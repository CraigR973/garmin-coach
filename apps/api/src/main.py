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

from src.config import Environment, settings
from src.logging_config import configure_logging
from src.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from src.rate_limit import limiter
from src.routers import (
    admin,
    auth,
    compare,
    groups,
    health,
    knockout_predictions,
    leaderboard,
    league_join_requests,
    league_memberships,
    leagues,
    matches,
    me,
    notifications,
    players,
    predictions,
    specials,
    squad,
    stats,
    surveys,
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


app = FastAPI(
    title="WC2026 Prediction League API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
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
app.include_router(admin.router)
app.include_router(me.router)
app.include_router(leagues.router)
app.include_router(league_memberships.router)
app.include_router(league_join_requests.router)
app.include_router(players.router)
app.include_router(players.league_router)
app.include_router(matches.router)
app.include_router(groups.router)
app.include_router(predictions.router)
app.include_router(knockout_predictions.router)
app.include_router(leaderboard.league_router)
app.include_router(leaderboard.global_router)
app.include_router(specials.router)
app.include_router(specials.admin_router)
app.include_router(squad.router)
app.include_router(stats.router)
app.include_router(stats.league_router)
app.include_router(compare.league_router)
app.include_router(notifications.router)
app.include_router(surveys.router)

if settings.environment == Environment.development:
    from src.routers import test_helpers  # noqa: PLC0415

    app.include_router(test_helpers.router)
