"""Auto-generated handover-doc export API (Batch 23 — the v3 capstone).

The portable "handover document" Mark used to hand-write, now assembled from the
app's living state. ``GET`` previews never write (#71); ``POST /run`` generates the
narrative through the Claude boundary and records it; ``GET /export`` downloads the
deterministic markdown so the doc is portable even without the model.

  GET  /api/v1/handover         — packet summary + deterministic markdown + stored narrative
  POST /api/v1/handover/run     — generate + store the narrative handover
  GET  /api/v1/handover/export  — download the portable markdown handover doc
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Analysis
from src.services.handover import (
    HandoverError,
    HandoverPreview,
    HandoverService,
)

router = APIRouter(prefix="/api/v1/handover", tags=["handover"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class StoredHandover(BaseModel):
    generatedAtUtc: str
    modelName: str | None
    promptVersion: str
    markdown: str


class HandoverData(BaseModel):
    subjectDate: str
    markdown: str
    packet: dict[str, Any]
    export: StoredHandover | None


class HandoverEnvelope(BaseModel):
    data: HandoverData
    meta: ApiMeta
    errors: list[ApiError]


def _stored(analysis: Analysis | None) -> StoredHandover | None:
    if analysis is None:
        return None
    return StoredHandover(
        generatedAtUtc=analysis.generated_at_utc.isoformat() + "Z",
        modelName=analysis.model_name,
        promptVersion=analysis.prompt_version,
        markdown=analysis.output_markdown,
    )


def _data(preview: HandoverPreview, export: Analysis | None) -> HandoverData:
    return HandoverData(
        subjectDate=preview.subject_date.isoformat(),
        markdown=preview.markdown,
        packet=preview.packet,
        export=_stored(export),
    )


@router.get("", response_model=HandoverEnvelope)
async def get_handover(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> HandoverEnvelope:
    service = HandoverService(db)
    preview = await service.preview(player, as_of=as_of)
    return HandoverEnvelope(
        data=_data(preview, preview.latest_export),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/run", response_model=HandoverEnvelope)
async def run_handover(
    player: CurrentUser,
    as_of: date | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> HandoverEnvelope:
    service = HandoverService(db)
    try:
        result = await service.run(player, as_of=as_of, force=force)
    except HandoverError as exc:
        return HandoverEnvelope(
            data=_data(await service.preview(player, as_of=as_of), None),
            meta=ApiMeta(generatedAtUtc=_generated_at()),
            errors=[ApiError(code="handover_generation_failed", detail=str(exc))],
        )
    return HandoverEnvelope(
        data=_data(result.preview, result.export),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.get("/export", response_class=PlainTextResponse)
async def export_handover(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Download the portable, deterministic markdown handover doc.

    Always available — it is rendered from the assembled packet without the model,
    so the export works (and faithfully reflects retained state) even without
    ``ANTHROPIC_API_KEY``.
    """
    service = HandoverService(db)
    preview = await service.preview(player, as_of=as_of)
    filename = f"handover-{preview.subject_date.isoformat()}.md"
    return PlainTextResponse(
        content=preview.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
