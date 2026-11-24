"""The self-improving loop's private queue and read-only feed (Batch 390, Decision #512).

G14's stage 2 (Decision #507). Every finding lands in ``improvement_items``, one row per
problem, whatever raised it: an operator alert, a degraded or failed job, a rating's
written correction, a coach pass-on, a figure dispute, and later the daily reviewer's
findings (391) and Mark's suggestions (392). A stable fingerprint folds repeats into the
one open row; a closed row's fingerprint opens a new one.

Craig's choices at batch-start (24 Nov 2026): the feed reaches back ``FEED_WINDOW_DAYS``
(14), so a leaked read token exposes two weeks at most; a closed row keeps its ``words``
(the only free text: Mark's words, the coach's summary) for ``WORDS_RETENTION_DAYS``
(90), then a daily job wipes them and the codes and dates stay.

Recording never breaks its caller: ``record_item`` uses its own session and swallows
errors, and ``queue_item`` (for sync code such as ``admin_alert``) schedules it on the
running loop and returns.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.coaching import Analysis, BriefMessage, Feedback, ManualEntry
from src.models.operations import ImprovementItem, JobRun

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: Craig's choices (24 Nov 2026, Decision #512).
FEED_WINDOW_DAYS: Final = 14
WORDS_RETENTION_DAYS: Final = 90

SOURCES: Final = frozenset(
    {"alert", "job_outcome", "correction", "pass_on", "dispute", "review", "suggestion"}
)
LANES: Final = frozenset({"fix_alone", "mark", "evidence", "craig"})
CLOSED_STATES: Final = frozenset({"verified", "undone", "dismissed"})
#: Where an item may go next. A closed item never reopens: a new occurrence opens a new row.
TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    "new": frozenset({"triaged", "dismissed", "escalated"}),
    "triaged": frozenset({"proposed", "with_mark", "dismissed", "escalated"}),
    "proposed": frozenset({"with_mark", "approved", "dismissed", "escalated"}),
    "with_mark": frozenset({"proposed", "approved", "dismissed"}),
    "approved": frozenset({"building", "dismissed", "escalated"}),
    "building": frozenset({"shipped", "proposed", "escalated"}),
    "shipped": frozenset({"verified", "undone"}),
    "escalated": frozenset({"triaged", "approved", "dismissed"}),
    "verified": frozenset(),
    "undone": frozenset(),
    "dismissed": frozenset(),
}
STATES: Final = frozenset(TRANSITIONS)

SUMMARY_MAX: Final = 240
KIND_MAX: Final = 64
FINGERPRINT_MAX: Final = 200
WORDS_MAX: Final = 4000
DETAIL_VALUE_MAX: Final = 120
#: Codes, dates and names only: the queue's ``detail`` never carries words or figures.
DETAIL_FIELDS: Final = (
    "reason",
    "artifact",
    "subject_date",
    "source",
    "step",
    "stage",
    "job",
    "status",
    "figure",
    "rating",
    "feedback_kind",
    "analysis_type",
)
#: The reads the daily reviewer checks.
REVIEWED_ANALYSIS_TYPES: Final = (
    "morning",
    "post_workout",
    "post_strength",
    "post_walk",
    "weekly_review",
    "monthly_review",
)
FEED_LIMIT_DEFAULT: Final = 100
FEED_LIMIT_MAX: Final = 300

#: Tests switch recording off (``conftest``); a test that wants it switches it back on.
RECORDING_ENABLED = True
_session_factory = AsyncSessionLocal
_PENDING: set[asyncio.Task[Any]] = set()


class TransitionError(ValueError):
    """An item cannot move from its state to the one asked for."""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def clean_detail(fields: Mapping[str, object] | None) -> dict[str, str]:
    """Keep only the allowlisted code fields, as short strings."""

    kept: dict[str, str] = {}
    for name in DETAIL_FIELDS:
        value = (fields or {}).get(name)
        if value is None or value == "" or isinstance(value, dict | list | tuple | set):
            continue
        kept[name] = str(value)[:DETAIL_VALUE_MAX]
    return kept


def clean_words(words: Mapping[str, object] | None) -> dict[str, str] | None:
    kept = {
        str(key)[:32]: str(value)[:WORDS_MAX]
        for key, value in (words or {}).items()
        if isinstance(value, str) and value.strip()
    }
    return kept or None


def check_transition(current: str, new: str) -> None:
    if new not in STATES:
        raise TransitionError(f"unknown state {new!r}")
    if new not in TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"an item cannot go from {current!r} to {new!r}")


async def record(
    session: AsyncSession,
    *,
    source: str,
    kind: str,
    summary: str,
    fingerprint: str,
    user_id: uuid.UUID | None = None,
    detail: Mapping[str, object] | None = None,
    words: Mapping[str, object] | None = None,
    source_refs: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> uuid.UUID:
    """Insert an item, or fold this occurrence into the open one with its fingerprint.

    The caller commits.
    """

    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    moment = now or _now()
    refs = {str(k)[:32]: str(v)[:80] for k, v in (source_refs or {}).items() if v is not None}
    inserted = insert(ImprovementItem).values(
        id=uuid.uuid4(),
        user_id=user_id,
        source=source,
        kind=kind[:KIND_MAX],
        fingerprint=fingerprint[:FINGERPRINT_MAX],
        state="new",
        summary=" ".join(summary.split())[:SUMMARY_MAX],
        detail=clean_detail(detail),
        words=clean_words(words),
        source_refs=refs,
        occurrences=1,
        first_seen_utc=moment,
        last_seen_utc=moment,
        updated_utc=moment,
    )
    statement = inserted.on_conflict_do_update(
        index_elements=[ImprovementItem.fingerprint],
        index_where=ImprovementItem.closed_utc.is_(None),
        set_={
            "occurrences": ImprovementItem.occurrences + 1,
            "last_seen_utc": moment,
            "updated_utc": moment,
            "summary": inserted.excluded.summary,
            "detail": inserted.excluded.detail,
            "words": func.coalesce(inserted.excluded.words, ImprovementItem.words),
            "source_refs": inserted.excluded.source_refs,
        },
    ).returning(ImprovementItem.id)
    item_id: uuid.UUID = (await session.execute(statement)).scalar_one()
    return item_id


async def record_item(**kwargs: Any) -> uuid.UUID | None:
    """``record`` in its own session and transaction. Never raises."""

    if not RECORDING_ENABLED:
        return None
    try:
        async with _session_factory() as session:
            item_id = await record(session, **kwargs)
            await session.commit()
            return item_id
    except Exception:
        log.warning(
            "improvement item not recorded",
            source=kwargs.get("source"),
            kind=kwargs.get("kind"),
            exc_info=True,
        )
        return None


def queue_item(**kwargs: Any) -> bool:
    """For sync code (``admin_alert``, the operator log routes): record on the running loop.

    Returns whether it was scheduled. Never raises and never blocks the caller.
    """

    if not RECORDING_ENABLED:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = loop.create_task(record_item(**kwargs))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return True


async def drain_pending() -> None:
    """Wait for queued recordings (tests, and a clean shutdown)."""

    if _PENDING:
        await asyncio.gather(*list(_PENDING), return_exceptions=True)


async def update_item(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    state: str | None = None,
    lane: str | None = None,
    proposal: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> ImprovementItem:
    """Move an item, set its lane or attach a proposal. The caller commits."""

    item = await session.get(ImprovementItem, item_id, with_for_update=True)
    if item is None:
        raise LookupError("no such item")
    moment = now or _now()
    if state is not None and state != item.state:
        check_transition(item.state, state)
        item.state = state
        if state in CLOSED_STATES:
            item.closed_utc = moment
    if lane is not None:
        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r}")
        item.lane = lane
    if proposal is not None:
        item.proposal = dict(proposal)
    item.updated_utc = moment
    return item


async def wipe_old_words(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Wipe the words of items closed more than 90 days ago; codes and dates stay."""

    moment = now or _now()
    cutoff = moment - timedelta(days=WORDS_RETENTION_DAYS)
    result = await session.execute(
        update(ImprovementItem)
        .where(ImprovementItem.closed_utc < cutoff, ImprovementItem.words.is_not(None))
        .values(words=None, updated_utc=moment)
    )
    wiped: int = result.rowcount if isinstance(result, CursorResult) else 0
    return wiped


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def serialize_item(item: ImprovementItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "source": item.source,
        "kind": item.kind,
        "state": item.state,
        "lane": item.lane,
        "summary": item.summary,
        "detail": item.detail,
        "words": item.words,
        "proposal": item.proposal,
        "sourceRefs": item.source_refs,
        "occurrences": item.occurrences,
        "firstSeenUtc": _iso(item.first_seen_utc),
        "lastSeenUtc": _iso(item.last_seen_utc),
        "updatedUtc": _iso(item.updated_utc),
        "closedUtc": _iso(item.closed_utc),
    }


# -- The read-only feed ----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class FeedCursor:
    """Where a page ended: the last event's time, type and id (in that order)."""

    at: datetime
    type: str
    id: str

    def encode(self) -> str:
        return f"{self.at.isoformat()}|{self.type}|{self.id}"

    @classmethod
    def decode(cls, raw: str) -> FeedCursor:
        parts = raw.split("|")
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise ValueError("bad cursor")
        return cls(datetime.fromisoformat(parts[0]).replace(tzinfo=None), parts[1], parts[2])


def window_start(now: datetime | None = None) -> datetime:
    return (now or _now()) - timedelta(days=FEED_WINDOW_DAYS)


def _event(event_type: str, at: datetime, event_id: object, **fields: Any) -> dict[str, Any]:
    return {"type": event_type, "at": at.isoformat(), "id": str(event_id), **fields}


async def build_feed(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    cursor: FeedCursor | None = None,
    limit: int = FEED_LIMIT_DEFAULT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Every chat turn, read, rating, check-in, unhealthy job and item in the window.

    Events come oldest first, ordered by time, type and id; a page ends at ``limit`` and
    hands back the cursor to continue from. Nothing older than the 14-day window is ever
    returned, whatever ``since`` or the cursor asks for.
    """

    moment = now or _now()
    limit = max(1, min(limit, FEED_LIMIT_MAX))
    floor = window_start(moment)
    start = max(floor, since.replace(tzinfo=None) if since else floor)
    if cursor is not None:
        start = max(start, cursor.at)
    per_source = limit + 1
    events: list[tuple[FeedCursor, dict[str, Any]]] = []

    def add(event_type: str, at: datetime, event_id: object, **fields: Any) -> None:
        key = FeedCursor(at, event_type, str(event_id))
        if cursor is not None and key <= cursor:
            return
        events.append((key, _event(event_type, at, event_id, **fields)))

    chats = await session.scalars(
        select(BriefMessage)
        .where(BriefMessage.created_utc >= start)
        .order_by(BriefMessage.created_utc, BriefMessage.id)
        .limit(per_source)
    )
    for message in chats:
        add(
            "chat",
            message.created_utc,
            message.id,
            role=message.role,
            content=message.content,
            analysisId=str(message.analysis_id) if message.analysis_id else None,
            originKind=message.origin_kind,
            originDate=message.origin_date.isoformat() if message.origin_date else None,
        )

    analyses = await session.scalars(
        select(Analysis)
        .where(
            Analysis.created_at >= start,
            Analysis.analysis_type.in_(REVIEWED_ANALYSIS_TYPES),
        )
        .order_by(Analysis.created_at, Analysis.id)
        .limit(per_source)
    )
    for analysis in analyses:
        add(
            "read",
            analysis.created_at,
            analysis.id,
            analysisType=analysis.analysis_type,
            subjectDate=analysis.subject_date.isoformat() if analysis.subject_date else None,
            promptVersion=analysis.prompt_version,
            modelName=analysis.model_name,
            verdict=analysis.verdict,
            outputMarkdown=analysis.output_markdown,
            hasPacket=bool(analysis.context_packet),
        )

    ratings = await session.scalars(
        select(Feedback)
        .where(Feedback.created_utc >= start)
        .order_by(Feedback.created_utc, Feedback.id)
        .limit(per_source)
    )
    for rating in ratings:
        add(
            "rating",
            rating.created_utc,
            rating.id,
            analysisId=str(rating.analysis_id),
            kind=rating.kind,
            rating=rating.rating,
            correctionText=rating.correction_text,
            reasonTags=list(rating.reason_tags or []),
        )

    check_ins = await session.scalars(
        select(ManualEntry)
        .where(ManualEntry.entry_at_utc >= start)
        .order_by(ManualEntry.entry_at_utc, ManualEntry.id)
        .limit(per_source)
    )
    for entry in check_ins:
        add(
            "checkIn",
            entry.entry_at_utc,
            entry.id,
            entryDate=entry.entry_date.isoformat(),
            subjectiveScore=entry.subjective_score,
            rpe=entry.rpe,
            feel=entry.feel,
            symptoms=entry.symptoms,
            notes=entry.notes,
        )

    unhealthy = await session.scalars(
        select(JobRun)
        .where(JobRun.started_at_utc >= start, JobRun.status.in_(("degraded", "failed")))
        .order_by(JobRun.started_at_utc, JobRun.id)
        .limit(per_source)
    )
    for run in unhealthy:
        add(
            "jobOutcome",
            run.started_at_utc,
            run.id,
            jobName=run.job_name,
            status=run.status,
            reason=run.reason,
        )

    items = await session.scalars(
        select(ImprovementItem)
        .where(ImprovementItem.updated_utc >= start)
        .order_by(ImprovementItem.updated_utc, ImprovementItem.id)
        .limit(per_source)
    )
    for item in items:
        add("item", item.updated_utc, item.id, item=serialize_item(item))

    events.sort(key=lambda pair: pair[0])
    page = events[:limit]
    more = len(events) > limit
    next_cursor = page[-1][0].encode() if page else (cursor.encode() if cursor else None)
    return {
        "events": [event for _, event in page],
        "nextCursor": next_cursor,
        "more": more,
        "windowStartUtc": floor.isoformat(),
        "windowDays": FEED_WINDOW_DAYS,
    }


async def packet_for(
    session: AsyncSession, analysis_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """The stored input a read was written from, only inside the feed's window."""

    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or analysis.created_at < window_start(now):
        return None
    return {
        "analysisId": str(analysis.id),
        "analysisType": analysis.analysis_type,
        "subjectDate": analysis.subject_date.isoformat() if analysis.subject_date else None,
        "contextPacket": analysis.context_packet,
    }


async def list_items(
    session: AsyncSession, *, open_only: bool = True, limit: int = FEED_LIMIT_DEFAULT
) -> list[dict[str, Any]]:
    statement = select(ImprovementItem).order_by(ImprovementItem.last_seen_utc.desc())
    if open_only:
        statement = statement.where(ImprovementItem.closed_utc.is_(None))
    rows: Iterable[ImprovementItem] = await session.scalars(
        statement.limit(max(1, min(limit, FEED_LIMIT_MAX)))
    )
    return [serialize_item(item) for item in rows]
