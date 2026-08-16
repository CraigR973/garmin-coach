"""The day's record means one thing: phase-key daily_metrics (Batch 205).

Revision ID: 028
Revises: 027
Create Date: 2026-08-16

``daily_metrics`` was one mutable row per ``(user_id, calendar_date)``. The
verdict is computed at wake, but the next morning's ``D-1..D-3`` re-sync
re-fetches each closed day and Garmin returns that day's *final* training
readiness — so the surviving row was the end-of-day one and every retrospective
consumer read it (CI191-02).

The unique key becomes ``(user_id, calendar_date, phase)``: the wake sync writes
``morning`` and the closed-day re-sync writes ``settled``, so the two
observations coexist instead of one overwriting the other. Column shape is
unchanged, which is what lets every consumer keep aggregating in Python.

**Backfill.** Historical ``morning`` rows are reconstructed from the earliest
stored morning ``analyses.context_packet -> 'dailyMetrics'`` for each date, which
is a faithful column-for-column mirror of the row as it stood at wake,
``recordedAtUtc`` included. Two honest limits, both deliberate:

* ``raw_payload`` was never captured in the packet, so a reconstructed row
  carries the same-date ``settled`` blob (or ``{}`` when there is none). The
  readings CI191-02 is about are all scalar columns and are exact; the fields
  read back out of ``raw_payload`` are day-level context (training status, step
  and intensity totals, VO2 fitness age, aggregate coverage). Rows written by
  the live wake sync from here on carry a genuine wake blob.
* A date with no stored morning read gets no ``morning`` row at all. Consumers
  fall back to ``settled`` rather than inventing a wake observation.

Reconstructed rows are identifiable by an ``updated_at`` equal to the migration
timestamp. The downgrade drops every ``morning`` row, so it is lossy for
natively-synced wake observations — the stored packets remain the record.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Batch 205 keeps the wake observation and the closed-day observation as
# separate rows; ``src.services.daily_metric_phase`` is the reading side.
MORNING_PHASE = "morning"
SETTLED_PHASE = "settled"

_BACKFILL_MORNING_ROWS = """
    INSERT INTO coach.daily_metrics (
        id,
        user_id,
        calendar_date,
        phase,
        recorded_at_utc,
        readiness_score,
        readiness_level,
        readiness_sleep_score,
        recovery_time_min,
        acute_load,
        training_status,
        hrv_last_night_avg_ms,
        hrv_weekly_avg_ms,
        hrv_status,
        hrv_baseline_low_ms,
        hrv_baseline_high_ms,
        resting_heart_rate_bpm,
        stress_avg,
        body_battery_charged,
        body_battery_drained,
        body_battery_end,
        weight_kg,
        vo2max,
        raw_payload,
        created_at,
        updated_at
    )
    SELECT
        gen_random_uuid(),
        wake.user_id,
        wake.calendar_date,
        'morning',
        (wake.packet ->> 'recordedAtUtc')::timestamp,
        (wake.packet ->> 'readinessScore')::int,
        wake.packet ->> 'readinessLevel',
        (wake.packet ->> 'readinessSleepScore')::int,
        (wake.packet ->> 'recoveryTimeMin')::int,
        (wake.packet ->> 'acuteLoad')::double precision,
        wake.packet ->> 'trainingStatus',
        (wake.packet ->> 'hrvLastNightAvgMs')::int,
        (wake.packet ->> 'hrvWeeklyAvgMs')::int,
        wake.packet ->> 'hrvStatus',
        (wake.packet ->> 'hrvBaselineLowMs')::int,
        (wake.packet ->> 'hrvBaselineHighMs')::int,
        (wake.packet ->> 'restingHeartRateBpm')::int,
        (wake.packet ->> 'stressAvg')::double precision,
        (wake.packet ->> 'bodyBatteryCharged')::int,
        (wake.packet ->> 'bodyBatteryDrained')::int,
        (wake.packet ->> 'bodyBatteryEnd')::int,
        (wake.packet ->> 'weightKg')::double precision,
        (wake.packet ->> 'vo2max')::double precision,
        COALESCE(settled.raw_payload, '{}'::jsonb),
        now(),
        now()
    FROM (
        SELECT DISTINCT ON (a.user_id, (a.context_packet -> 'dailyMetrics' ->> 'calendarDate'))
            a.user_id,
            (a.context_packet -> 'dailyMetrics' ->> 'calendarDate')::date AS calendar_date,
            a.context_packet -> 'dailyMetrics' AS packet
        FROM coach.analyses a
        WHERE a.analysis_type = 'morning'
          AND jsonb_typeof(a.context_packet -> 'dailyMetrics') = 'object'
          AND (a.context_packet -> 'dailyMetrics' ->> 'calendarDate') IS NOT NULL
        -- The wake read, not a later same-day regeneration built on newer data.
        ORDER BY
            a.user_id,
            (a.context_packet -> 'dailyMetrics' ->> 'calendarDate'),
            a.generated_at_utc ASC,
            a.created_at ASC
    ) AS wake
    LEFT JOIN coach.daily_metrics settled
           ON settled.user_id = wake.user_id
          AND settled.calendar_date = wake.calendar_date
          AND settled.phase = 'settled'
    ON CONFLICT ON CONSTRAINT uq_daily_metrics_user_date_phase DO NOTHING
"""


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    # Every existing row is the survivor of the closed-day re-sync.
    op.add_column(
        "daily_metrics",
        sa.Column(
            "phase",
            sa.String(16),
            nullable=False,
            server_default=SETTLED_PHASE,
        ),
        schema="coach",
    )
    op.create_check_constraint(
        "ck_daily_metrics_phase",
        "daily_metrics",
        "phase IN ('morning', 'settled')",
        schema="coach",
    )
    op.drop_constraint(
        "uq_daily_metrics_user_date",
        "daily_metrics",
        type_="unique",
        schema="coach",
    )
    op.create_unique_constraint(
        "uq_daily_metrics_user_date_phase",
        "daily_metrics",
        ["user_id", "calendar_date", "phase"],
        schema="coach",
    )
    op.execute(_BACKFILL_MORNING_ROWS)
    # The default existed only to phase the existing rows. Leaving it in place
    # would let a writer that forgot to declare a phase silently reintroduce the
    # overwrite this migration removes.
    op.alter_column(
        "daily_metrics",
        "phase",
        server_default=None,
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    # The settled row is the one the pre-Batch-205 schema kept, so dropping the
    # wake rows restores a unique (user_id, calendar_date) before the constraint
    # is put back.
    op.execute("DELETE FROM coach.daily_metrics WHERE phase = 'morning'")
    op.drop_constraint(
        "uq_daily_metrics_user_date_phase",
        "daily_metrics",
        type_="unique",
        schema="coach",
    )
    op.create_unique_constraint(
        "uq_daily_metrics_user_date",
        "daily_metrics",
        ["user_id", "calendar_date"],
        schema="coach",
    )
    op.drop_constraint(
        "ck_daily_metrics_phase",
        "daily_metrics",
        type_="check",
        schema="coach",
    )
    op.drop_column("daily_metrics", "phase", schema="coach")
