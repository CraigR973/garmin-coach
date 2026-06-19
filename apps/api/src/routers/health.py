import structlog
from fastapi import APIRouter, Response
from sqlalchemy import text

from src.config import settings
from src.database import AsyncSessionLocal

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
