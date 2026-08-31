"""The budgets and locks that decide what a slow generation costs (Batch 232).

Every assertion here descends from one morning. On 2026-08-30, fifteen attempts
queued on the single advisory key for ``morning:<mark>:2026-08-30``; eight
acquired it after 40.4s to 117.6s, and seven were killed by Postgres at the
120s ``statement_timeout`` without ever generating anything. Each queued attempt
also held a session-mode pooler client slot for its whole wait, and Supavisor
refused new clients eight times in the same window.

None of that was visible to a unit test, because the relationships involved —
between a lock and a paid call, and between three timeout budgets owned by three
different batches — were written in comments rather than asserted anywhere.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from src.config import Environment, Settings, settings
from src.database import engine
from src.models.profile import Profile, UserRole
from src.services.generation_requests import (
    OBSERVED_STATEMENT_TIMEOUT,
    GenerationRequestInProgress,
    claim_generation_request,
    lease_duration,
    timeout_ordering,
    validate_timeout_ordering,
)
from src.services.reviews import PERIOD_WEEKLY, ReviewService


class RefusingLockSession:
    """A session whose advisory-lock attempt fails, recording what was asked.

    The refusal is the first statement either code path runs, so nothing else on
    the session is ever touched — which is the point: a caller that cannot have
    the scope must be answered before it does any work at all.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(str(statement.compile(dialect=postgresql.dialect())))
        return False

    @property
    def only_statement(self) -> str:
        assert len(self.statements) == 1, self.statements
        return self.statements[0]


def _profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Budget",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_claiming_a_scope_never_waits_for_the_lock() -> None:
    """The claim takes the *try* variant, so no attempt can queue behind a paid call.

    The blocking ``pg_advisory_xact_lock`` is what made a queued attempt
    indistinguishable from a hung one: with ``lock_timeout`` at 0 in production,
    its only bound was the 120s statement timeout, and being cancelled there is
    reported as a generic database error rather than "someone else has this".
    """

    session = RefusingLockSession()

    with pytest.raises(GenerationRequestInProgress):
        async with claim_generation_request(
            session,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            request_identity="identity",
            generation_kind="morning",
            lease_scope="morning:someone:2026-08-30",
        ):  # pragma: no cover - the body must never run
            raise AssertionError("a refused claim must not yield")

    assert "pg_try_advisory_xact_lock" in session.only_statement
    assert "pg_advisory_xact_lock(" not in session.only_statement


@pytest.mark.asyncio
async def test_generating_a_review_never_waits_for_the_lock() -> None:
    """The weekly review has the same shape, on the one path built to overlap.

    Decision #266 runs the Railway ``weekly-review`` cron *and* the in-process
    APScheduler job on purpose, so one of them losing the artifact lock is the
    designed outcome and has to be cheap.
    """

    session = RefusingLockSession()

    with pytest.raises(GenerationRequestInProgress):
        await ReviewService(session).run(  # type: ignore[arg-type]
            _profile(),
            PERIOD_WEEKLY,
            as_of=date(2026, 8, 30),
        )

    assert "pg_try_advisory_xact_lock" in session.only_statement
    assert "pg_advisory_xact_lock(" not in session.only_statement


def test_the_three_budgets_are_ordered_at_the_configured_values() -> None:
    ordering = timeout_ordering()

    assert ordering.holds, ordering.describe()
    # Spelled out rather than left to ``holds``, so a future edit to the property
    # cannot quietly weaken what this test claims to check.
    assert ordering.lease > ordering.anthropic_read
    assert ordering.lease > ordering.statement_timeout
    assert ordering.lease < ordering.brief_generation_stale_after
    assert ordering.statement_timeout == OBSERVED_STATEMENT_TIMEOUT
    validate_timeout_ordering()


def test_the_lease_follows_a_retuned_read_budget_rather_than_a_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ANTHROPIC_READ_TIMEOUT_SECONDS`` is env-tunable, so the ordering must
    hold for whatever it is set to — not merely for the value in ``config.py``.

    This is the exact failure Batch 234 introduced and this batch closes: it
    raised the read budget from 60s to 300s and left the lease at a hardcoded
    180s, so the lease became shorter than the call it exists to cover.
    """

    monkeypatch.setattr(settings, "anthropic_read_timeout_seconds", 450.0)

    assert lease_duration() == timedelta(seconds=450.0 + settings.generation_lease_overhead_seconds)
    ordering = timeout_ordering()
    assert ordering.anthropic_read == timedelta(seconds=450.0)
    assert ordering.holds, ordering.describe()
    validate_timeout_ordering()


def test_a_read_budget_that_outruns_the_lease_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lease shorter than the paid call it covers is a lease that lies."""

    monkeypatch.setattr(settings, "anthropic_read_timeout_seconds", 300.0)
    monkeypatch.setattr(settings, "generation_lease_overhead_seconds", -10.0)

    assert not timeout_ordering().holds
    with pytest.raises(ValueError, match="out of order"):
        validate_timeout_ordering()


def test_a_lease_outliving_the_stale_guard_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 144's orphan guard must fire *after* the lease has freed the scope.

    Otherwise the app offers Mark a retry it will then refuse with a 409 — the
    UI says the generation is stale while the request row still says it is live.
    """

    monkeypatch.setattr(settings, "brief_generation_stale_after_minutes", 5)

    assert timeout_ordering().lease > timedelta(minutes=5)
    with pytest.raises(ValueError, match="out of order"):
        validate_timeout_ordering()


def test_the_pool_cannot_provision_above_the_pooler_ceiling() -> None:
    """``pool_size + max_overflow`` has to fit inside what Supavisor grants.

    It did not: 10 + 10 against a session-mode limit of 15. The excess is not
    refused at startup but on the connection that happens to be the sixteenth,
    which is why it surfaced as eight scattered FATALs during a retry storm
    rather than as a configuration error anyone could see.
    """

    budget = settings.db_pooler_client_limit - settings.db_pooler_reserved_connections

    assert settings.db_pool_size + settings.db_max_overflow <= budget
    # The engine must actually read the settings, not carry its own literals.
    assert engine.pool.size() == settings.db_pool_size


def test_a_pool_provisioned_above_the_pooler_ceiling_is_refused() -> None:
    # The previous values, restated: 10 + 10 against a 15-client session-mode
    # pooler. ``environment`` is pinned so the secrets validator (which runs
    # first) cannot pre-empt the one under test.
    with pytest.raises(ValidationError, match="pooler budget"):
        Settings(environment=Environment.development, db_pool_size=10, db_max_overflow=10)


def test_reserved_connections_leave_room_for_the_other_clients() -> None:
    """The API is not the only claim on the tenant's client budget.

    The ``weekly-review`` cron container runs the same code with its own engine,
    every deploy runs ``alembic upgrade head`` at boot, the nightly ``pg_dump``
    opens its own connection, and ``railway run`` / ``railway ssh`` sessions add
    more. A reserve of zero would let the API alone consume every slot.
    """

    assert settings.db_pooler_reserved_connections > 0
    assert settings.db_pooler_reserved_connections < settings.db_pooler_client_limit


def test_the_read_budget_stays_under_the_wall_the_stale_guard_imposes() -> None:
    """Batch 233.6: the ceiling Batch 232 put on ``anthropic_read_timeout_seconds``.

    Batch 233 raised ``anthropic_max_tokens`` 4096 → 24576 to make room for
    Sonnet 5's adaptive thinking, and the read budget is derived from that
    ceiling. The derivation is not free to grow: the lease is
    ``read + generation_lease_overhead_seconds`` and must expire before Batch
    144's stale-after guard, so ``read`` has a hard upper bound of
    ``stale_after − overhead`` — 600s at today's 720s/120s. This asserts the
    bound explicitly rather than leaving a future retune to discover it as a
    boot failure in production.
    """

    wall = timedelta(minutes=settings.brief_generation_stale_after_minutes) - timedelta(
        seconds=settings.generation_lease_overhead_seconds
    )

    assert wall == timedelta(seconds=600)
    assert timeout_ordering().anthropic_read < wall


def test_a_read_budget_at_the_wall_refuses_to_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wall is enforced, not merely documented."""

    monkeypatch.setattr(settings, "anthropic_read_timeout_seconds", 600.0)

    assert not timeout_ordering().holds
    with pytest.raises(ValueError, match="out of order"):
        validate_timeout_ordering()
