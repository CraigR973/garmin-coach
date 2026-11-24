"""The loop's private, token-gated feed and item endpoints (Batch 390, Decision #512).

The daily reviewer (Batch 391) reads Mark's recent conversations, reads, ratings and
check-ins here, with the stored packet behind any read, and files findings. Two
secrets gate it: a read token for the ``GET`` routes and a separate write token for
filing and moving items, compared in constant time. With a token unset its routes
answer 404, so until Craig sets them with 391 nothing of Mark's is exposed. Nothing
reaches back further than 14 days (Craig's choice).
"""

from __future__ import annotations

import hmac
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models.operations import ImprovementItem
from src.rate_limit import limiter
from src.services import improvement_items as items

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])

PROPOSAL_MAX_BYTES = 16_000
DETAIL_MAX_KEYS = 30


def _token_gate(setting: str) -> Callable[[Request], Awaitable[None]]:
    async def gate(request: Request) -> None:
        expected = str(getattr(settings, setting)).strip()
        if not expected:
            # The feed is off: answer as if the route did not exist.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        header = request.headers.get("Authorization", "")
        supplied = header[7:].strip() if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return gate


#: Named, so the route-auth inventory can tell machine-token routes from open ones.
read_gate = _token_gate("ops_feed_read_token")
write_gate = _token_gate("ops_feed_write_token")
require_read = Depends(read_gate)
require_write = Depends(write_gate)


def _envelope(data: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {"generatedAtUtc": datetime.now(UTC).isoformat()},
        "errors": [],
    }


class ItemIn(BaseModel):
    source: Literal["review", "suggestion"]
    kind: str = Field(min_length=1, max_length=items.KIND_MAX)
    summary: str = Field(min_length=1, max_length=items.SUMMARY_MAX)
    fingerprint: str = Field(min_length=1, max_length=items.FINGERPRINT_MAX)
    detail: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    words: dict[str, str] | None = None
    sourceRefs: dict[str, str] = Field(default_factory=dict)

    @field_validator("detail")
    @classmethod
    def _bounded_detail(
        cls, value: dict[str, str | int | float | bool | None]
    ) -> dict[str, str | int | float | bool | None]:
        if len(value) > DETAIL_MAX_KEYS:
            raise ValueError("too many detail fields")
        return value


class ItemPatch(BaseModel):
    state: (
        Literal[
            "new",
            "triaged",
            "proposed",
            "with_mark",
            "approved",
            "building",
            "shipped",
            "verified",
            "undone",
            "escalated",
            "dismissed",
        ]
        | None
    ) = None
    lane: Literal["fix_alone", "mark", "evidence", "craig"] | None = None
    proposal: dict[str, Any] | None = None

    @field_validator("proposal")
    @classmethod
    def _bounded_proposal(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > PROPOSAL_MAX_BYTES:
            raise ValueError("proposal too large")
        return value


@router.get("/review-feed", dependencies=[require_read])
@limiter.limit("60/minute")
async def review_feed(
    request: Request,
    since: datetime | None = None,
    cursor: str | None = None,
    limit: int = items.FEED_LIMIT_DEFAULT,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    parsed: items.FeedCursor | None = None
    if cursor:
        try:
            parsed = items.FeedCursor.decode(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Bad cursor") from exc
    feed = await items.build_feed(db, since=since, cursor=parsed, limit=limit)
    return _envelope(feed)


@router.get("/packets/{analysis_id}", dependencies=[require_read])
@limiter.limit("120/minute")
async def read_packet(
    request: Request, analysis_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    packet = await items.packet_for(db, analysis_id)
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return _envelope(packet)


@router.get("/items", dependencies=[require_read])
@limiter.limit("60/minute")
async def read_items(
    request: Request,
    state: Literal["open", "all"] = "open",
    limit: int = items.FEED_LIMIT_DEFAULT,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = await items.list_items(db, open_only=state == "open", limit=limit)
    return _envelope({"items": rows})


@router.post("/items", dependencies=[require_write], status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def file_item(
    request: Request, payload: ItemIn, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    item_id = await items.record(
        db,
        source=payload.source,
        kind=payload.kind,
        summary=payload.summary,
        fingerprint=f"{payload.source}:{payload.fingerprint}",
        detail=payload.detail,
        words=payload.words,
        source_refs=payload.sourceRefs,
    )
    await db.commit()
    row = await db.get(ImprovementItem, item_id)
    assert row is not None
    await db.refresh(row)
    return _envelope({"item": items.serialize_item(row)})


@router.patch("/items/{item_id}", dependencies=[require_write])
@limiter.limit("30/minute")
async def move_item(
    request: Request, item_id: uuid.UUID, payload: ItemPatch, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        row = await items.update_item(
            db, item_id, state=payload.state, lane=payload.lane, proposal=payload.proposal
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found") from exc
    except (items.TransitionError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _envelope({"item": items.serialize_item(row)})
