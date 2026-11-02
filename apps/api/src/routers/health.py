import structlog
from fastapi import APIRouter, Response
from sqlalchemy import text

from src.config import settings
from src.database import AsyncSessionLocal
from src.services.job_ledger_freshness import collect_watchdog_report

router = APIRouter(prefix="/api/v1/health", tags=["health"])

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@router.get("")
async def health() -> dict[str, str]:
    sha = settings.railway_git_commit_sha or "unknown"
    return {"status": "ok", "sha": sha}


@router.get("/ready")
async def ready(response: Response) -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "db": "ok"}
    except Exception:
        log.warning("readiness check failed — db unreachable")
        response.status_code = 503
        return {"status": "not_ready", "db": "unreachable"}


@router.get("/jobs")
async def jobs(response: Response) -> dict[str, object]:
    """What the external watchdog reads (Batch 365.1, DS357-02).

    Read-only and unauthenticated, so it carries problem codes only: a stale or failing
    job's name, a refused provider, a failed brief's reason. No profile, value or time
    from his data. ``status`` is ``alert`` while any problem stands; a database it cannot
    reach is a 503, as ``/ready`` is.
    """
    try:
        async with AsyncSessionLocal() as session:
            report = await collect_watchdog_report(session)
    except Exception:
        log.warning("watchdog report failed — db unreachable")
        response.status_code = 503
        return {"status": "alert", "problems": ["db_unreachable"]}
    return {"status": report.status, "problems": list(report.problems)}
