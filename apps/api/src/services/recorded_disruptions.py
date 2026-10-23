"""What the app has on record as disturbing Mark's recovery numbers (Batch 347).

Mark's strongest complaint of 12–19 Oct 2026 was the app treating the obvious effects
of his 27 Sep–6 Oct holiday and a night away as concerns. The coach chat now leads
with a recorded disruption (v27, Decision #430), but the weekly review never saw one:
its packet held no holiday dates, no check-in and no notes reading, so the 11 Oct
review blamed the week's caution on something else. The morning brief could see the
holiday, but only in the knowledge base and in the structural signal's bookkeeping,
which its prompt says not to mention unless that signal fired.

Both stored reads now carry the same record, built here once, so they cannot disagree
about what happened. A disruption is one of three things, and nothing else may be:

* **a holiday** he entered, by the mornings he woke away. Overnight away is
  end-exclusive (Decision #213): a 27 Sep–6 Oct holiday is the nights of 27 Sep to
  5 Oct, waking 28 Sep to 6 Oct. The dates come from ``away_nights.holiday_wake_dates``,
  the helper the chronic cards and the driver correlation use (Decision #429), so the
  three cannot disagree about which mornings were away.
* **travel, alcohol or illness** that the notes reader (Batch 297) found in a morning
  check-in's note for *now* or *last night* — the bound ``chronic_patterns``
  already applies to an acute cause, through the same ``reading_causes``. A note
  that places one earlier ("post holiday") describes the past and counts for nothing.
* **illness** he gave as his answer to the check-in's symptom question (Batch 294).

Illness here is a cold, fever or aches, never chest or heart symptoms (Craig, 22 Oct;
``symptom_check.ILLNESS_SYMPTOM_ANSWERS``). A chest or heart report is a safety floor
with its own follow-up (Batch 315), never a cause to wait out. A note that says only
that he feels unwell is not illness here either, although the two-Reds check counts
it (Decision #368): "unwell" can be a hangover or a poor night, and a dip it would
explain away stays a concern instead, which is the cautious way to be wrong.

A late meal is recorded nowhere structured: it exists only in his own words, which
the morning brief sees for today and the review never sees.

Each item says when his numbers should be back if it was the cause: about a week after
its last morning (``SETTLE_DAYS``), which is also when a 7-day HRV average stops
holding any of its nights. The rule that reads it is ``coach_policy.KNOWN_DISRUPTION_RULE``.

Every function but the loader is pure.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import CheckInReading, ManualEntry
from src.services.away_nights import holiday_wake_dates
from src.services.chronic_patterns import reading_causes
from src.services.holiday_pause import HolidayWindow
from src.services.notes_reader import notes_hash
from src.services.symptom_check import ILLNESS_SYMPTOM_ANSWERS, SYMPTOM_LABELS

Reason = Literal["holiday", "travel", "alcohol", "illness"]

#: His numbers should be back in his usual range about a week after the last morning a
#: disruption covered (v27's wording, Decision #430).
SETTLE_DAYS: Final = 7
#: The morning brief looks back over the 28 mornings to its date, the window its
#: chronic cards count misses over.
MORNING_LOOKBACK_DAYS: Final = 27
#: A review looks back three weeks before its period, so a disruption that ended
#: shortly before the period, or that the four-week warnings still hold, is in view.
REVIEW_LOOKBACK_DAYS: Final = 21
#: His quoted words per item, at most: the reader caps each quote at 200 characters.
MAX_WORDS_PER_ITEM: Final = 3

#: The causes a check-in note can record here. ``deliberate_rest`` and
#: ``training_load`` are reasons for a number, not disruptions of it.
_CHECK_IN_REASONS: Final[frozenset[str]] = frozenset({"travel", "alcohol", "illness"})
#: The reader's flags that are not illness here (module docstring): feeling unwell is
#: dropped before ``reading_causes`` reads a note. Chest or heart never was illness.
_NOT_ILLNESS_FLAGS: Final[frozenset[str]] = frozenset({"unwell"})

STAGE_ONGOING: Final = "ongoing"
STAGE_SETTLING: Final = "ended within the last week"
STAGE_PAST: Final = "ended more than a week ago"

BASIS_HOLIDAY: Final = "the holiday dates he entered in the app"
BASIS_NOTE: Final = "his own words in a check-in note"
BASIS_SYMPTOM_ANSWER: Final = "his answer to the check-in's symptom question"

MEANING: Final = (
    "What the app has on record as disturbing his recovery numbers between from and asOf: "
    "holiday nights away from the dates he entered, and travel, alcohol or illness (a "
    "cold, fever or aches, never chest or heart symptoms) that his check-ins report for "
    "now or last night. firstMorning to lastMorning are the "
    "mornings it covers; settleBy is a week after the last, when his numbers should be "
    "back in his usual range if it was the cause. A disruption not listed here is not "
    "on record."
)


@dataclass(frozen=True, slots=True)
class CheckInRecord:
    """One morning check-in as this module needs it.

    ``reading`` is the notes reader's reading of the note the check-in carries *now*,
    or ``None`` when that version of the note has no reading.
    """

    entry_date: date
    symptoms: str | None = None
    reading: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RecordedDisruption:
    reason: Reason
    start_date: date
    end_date: date
    first_morning: date
    last_morning: date
    basis: str
    words: tuple[str, ...] = ()

    @property
    def settle_by(self) -> date:
        return self.last_morning + timedelta(days=SETTLE_DAYS)

    def stage(self, as_of: date) -> str:
        if as_of <= self.last_morning:
            return STAGE_ONGOING
        if as_of <= self.settle_by:
            return STAGE_SETTLING
        return STAGE_PAST

    def to_packet(self, *, as_of: date) -> dict[str, Any]:
        packet: dict[str, Any] = {
            "reason": self.reason,
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "firstMorning": self.first_morning.isoformat(),
            "lastMorning": self.last_morning.isoformat(),
            "settleBy": self.settle_by.isoformat(),
            "stage": self.stage(as_of),
            "basis": self.basis,
        }
        if self.words:
            packet["words"] = list(self.words)
        return packet


@dataclass(frozen=True, slots=True)
class RecordedDisruptions:
    window_start: date
    as_of: date
    items: tuple[RecordedDisruption, ...] = ()

    def to_packet(self) -> dict[str, Any]:
        return {
            "from": self.window_start.isoformat(),
            "asOf": self.as_of.isoformat(),
            "meaning": MEANING,
            "items": [item.to_packet(as_of=self.as_of) for item in self.items],
        }


def holiday_disruptions(windows: Sequence[HolidayWindow]) -> list[RecordedDisruption]:
    """One item per holiday he slept away for, dated by the mornings he woke away.

    A window with no night away (it starts and ends on one day) is not a disruption.
    A resumed window still counts: it records where he was on its dates.
    """

    items: list[RecordedDisruption] = []
    for window in windows:
        mornings = holiday_wake_dates(window.start_date, window.end_date)
        if not mornings:
            continue
        items.append(
            RecordedDisruption(
                reason="holiday",
                start_date=window.start_date,
                end_date=window.end_date,
                first_morning=mornings[0],
                last_morning=mornings[-1],
                basis=BASIS_HOLIDAY,
            )
        )
    return items


def check_in_disruptions(check_ins: Iterable[CheckInRecord]) -> list[RecordedDisruption]:
    """Travel, alcohol and illness from his check-ins, consecutive days merged.

    Kept apart by where they came from, so each item's basis is exact: an illness he
    tapped and an illness he wrote are two items even on neighbouring days.
    """

    by_kind: dict[tuple[str, str], dict[date, list[str]]] = {}
    for check_in in check_ins:
        if check_in.symptoms in ILLNESS_SYMPTOM_ANSWERS:
            words = SYMPTOM_LABELS[str(check_in.symptoms)]
            by_kind.setdefault(("illness", BASIS_SYMPTOM_ANSWER), {}).setdefault(
                check_in.entry_date, []
            ).append(words)
        if check_in.reading is None:
            continue
        reading = {
            flag: value
            for flag, value in check_in.reading.items()
            if flag not in _NOT_ILLNESS_FLAGS
        }
        for cause, words in reading_causes(reading):
            if cause not in _CHECK_IN_REASONS:
                continue
            by_kind.setdefault((cause, BASIS_NOTE), {}).setdefault(check_in.entry_date, []).append(
                words
            )

    items: list[RecordedDisruption] = []
    for (reason, basis), days in by_kind.items():
        for run in _consecutive_runs(sorted(days)):
            quoted = _distinct(word for day in run for word in days[day])
            items.append(
                RecordedDisruption(
                    reason=_as_reason(reason),
                    start_date=run[0],
                    end_date=run[-1],
                    first_morning=run[0],
                    last_morning=run[-1],
                    basis=basis,
                    words=quoted[:MAX_WORDS_PER_ITEM],
                )
            )
    return items


def build_recorded_disruptions(
    *,
    windows: Sequence[HolidayWindow],
    check_ins: Iterable[CheckInRecord],
    window_start: date,
    as_of: date,
) -> RecordedDisruptions:
    """Every disruption whose mornings touch ``window_start`` to ``as_of``, in date order.

    A night away a check-in reports inside a holiday's mornings adds nothing: the
    holiday already covers it.
    """

    holidays = holiday_disruptions(windows)
    holiday_mornings = {
        item.first_morning + timedelta(days=offset)
        for item in holidays
        for offset in range((item.last_morning - item.first_morning).days + 1)
    }
    items = [
        *holidays,
        *(
            item
            for item in check_in_disruptions(check_ins)
            if not (item.reason == "travel" and _all_mornings_in(item, holiday_mornings))
        ),
    ]
    in_window = [
        item for item in items if item.first_morning <= as_of and item.last_morning >= window_start
    ]
    in_window.sort(key=lambda item: (item.first_morning, item.last_morning, item.reason))
    return RecordedDisruptions(window_start=window_start, as_of=as_of, items=tuple(in_window))


async def load_recorded_disruptions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    windows: Sequence[HolidayWindow],
    window_start: date,
    as_of: date,
) -> RecordedDisruptions:
    """The record for ``window_start`` to ``as_of``, from his stored check-ins.

    Only the columns this needs are read: a check-in row also carries his food,
    supplements and bedroom set-up, none of which is a disruption.
    """

    entries = (
        await session.execute(
            select(ManualEntry.id, ManualEntry.entry_date, ManualEntry.notes, ManualEntry.symptoms)
            .where(
                ManualEntry.user_id == user_id,
                ManualEntry.entry_date >= window_start,
                ManualEntry.entry_date <= as_of,
                ManualEntry.planned_workout_id.is_(None),
                ManualEntry.activity_id.is_(None),
            )
            .order_by(ManualEntry.entry_date, ManualEntry.entry_at_utc)
        )
    ).all()
    note_versions = {
        entry_id: digest
        for entry_id, _, notes, _ in entries
        if (digest := notes_hash(notes)) is not None
    }
    readings: dict[uuid.UUID, Mapping[str, Any]] = {}
    if note_versions:
        rows = await session.execute(
            select(
                CheckInReading.manual_entry_id,
                CheckInReading.notes_sha256,
                CheckInReading.reading,
            ).where(
                CheckInReading.manual_entry_id.in_(list(note_versions)),
                CheckInReading.status == "read",
            )
        )
        for entry_id, digest, reading in rows.all():
            # A reading counts only for the version of the note it was made from.
            if note_versions.get(entry_id) == digest and isinstance(reading, Mapping):
                readings[entry_id] = reading
    check_ins = [
        CheckInRecord(entry_date=entry_date, symptoms=symptoms, reading=readings.get(entry_id))
        for entry_id, entry_date, _, symptoms in entries
    ]
    return build_recorded_disruptions(
        windows=windows, check_ins=check_ins, window_start=window_start, as_of=as_of
    )


def _consecutive_runs(days: Sequence[date]) -> list[list[date]]:
    runs: list[list[date]] = []
    for day in days:
        if runs and day - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


def _distinct(words: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for word in words:
        cleaned = word.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return tuple(seen)


def _all_mornings_in(item: RecordedDisruption, mornings: set[date]) -> bool:
    span = (item.last_morning - item.first_morning).days + 1
    return all(item.first_morning + timedelta(days=offset) in mornings for offset in range(span))


def _as_reason(value: str) -> Reason:
    if value == "travel":
        return "travel"
    if value == "alcohol":
        return "alcohol"
    if value == "illness":
        return "illness"
    raise ValueError(f"not a check-in disruption: {value!r}")
