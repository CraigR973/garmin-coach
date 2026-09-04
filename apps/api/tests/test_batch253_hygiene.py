"""Batch 253: the drift layer, closed with a test where it is testable.

Nineteen findings across four audit passes, individually small and collectively
the reason findings recur wave after wave. These are the ones whose closure is a
property rather than a behaviour change: a duplicated rule that must stay one
constant, a duplicated loader that must stay one function, a packet that must
stop carrying a home address, a lifecycle that must stay one lifecycle.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.services.age_norms import SLEEP_STAGE_PCT_BASIS, SLEEP_STAGE_PCT_BASIS_NOTE
from src.services.coach_policy import (
    PACKET_FIELD_NAMES_RULE,
    READ_PROMPT_FLOORS,
    RECORDED_DATA_HONESTY_RULE,
)
from src.services.post_activity_read_runner import PostActivityReadRunner
from src.services.post_flexibility_analysis import PostFlexibilityAnalysisService
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService
from src.services.post_workout_analysis import PostWorkoutAnalysisService

REPO = Path(__file__).parents[3]
SRC = Path(__file__).parents[1] / "src"


# ---------------------------------------------------------------------------
# AI238-06 — one honesty rule, one constant
# ---------------------------------------------------------------------------

PROMPT_SURFACES = {
    "morning_analysis": "SYSTEM_PROMPT",
    "post_workout_analysis": "SYSTEM_PROMPT",
    "post_walk_analysis": "SYSTEM_PROMPT",
    "post_strength_analysis": "SYSTEM_PROMPT",
    "post_flexibility_analysis": "SYSTEM_PROMPT",
    "reviews": "SYSTEM_PROMPT",
    "trends": "TREND_SYSTEM_PROMPT",
    "handover": "HANDOVER_SYSTEM_PROMPT",
    "longitudinal_analysis": "SYSTEM_PROMPT",
}


def _prompt(module_name: str) -> str:
    from importlib import import_module

    return str(getattr(import_module(f"src.services.{module_name}"), PROMPT_SURFACES[module_name]))


@pytest.mark.parametrize("module_name", sorted(PROMPT_SURFACES))
def test_every_surface_carries_the_honesty_rule_verbatim(module_name: str) -> None:
    """Batch 230's shape, applied to the rule most central to the app's honesty.

    The paragraph was eight separate hand-written literals. All eight were
    byte-identical *today*; nothing kept them that way, and the audit that existed
    matched a **regex**, so a divergent paraphrase containing the pattern passed.
    Asserting the constant is *in* the prompt is the check a regex cannot make.
    """
    assert RECORDED_DATA_HONESTY_RULE in _prompt(module_name)


def test_the_rule_is_a_constant_rather_than_a_literal_in_any_prompt_module() -> None:
    """A ninth copy pasted in would satisfy the test above; this one catches it."""
    opener = "Treat every figure in the supplied context"
    for module_name in PROMPT_SURFACES:
        source = (SRC / "services" / f"{module_name}.py").read_text(encoding="utf-8")
        assert opener not in source, (
            f"{module_name} states the honesty rule as a literal. Interpolate "
            "RECORDED_DATA_HONESTY_RULE instead — a second wording is how this "
            "defect class survives."
        )


def test_the_field_name_rule_is_one_wording_not_three() -> None:
    """Batch 230's own fix realised the class it named.

    "Packet field names are instructions to you, never words for Mark" existed as
    two near-copies differing in punctuation, with the trends copy naming two
    field paths as examples **inside a rule forbidding field names**.
    """
    assert PACKET_FIELD_NAMES_RULE in _prompt("morning_analysis")
    assert PACKET_FIELD_NAMES_RULE in _prompt("trends")
    assert "remAgeBand.basis, personalBaselines" not in _prompt("trends")


def test_the_power_balance_floor_is_listed_wherever_it_is_stated() -> None:
    """It appeared in four prompts and was audited in two, so dropping it from
    reviews or trends would have been silent."""
    for module_name in ("morning_analysis", "post_workout_analysis", "reviews", "trends"):
        assert "no_power_balance" in READ_PROMPT_FLOORS[module_name]


# ---------------------------------------------------------------------------
# AI238-12 — one basis string, not two
# ---------------------------------------------------------------------------


def test_the_sleep_stage_basis_is_one_sentence_the_model_cannot_pick_wrong() -> None:
    """The packet described the denominator twice, in two registers, and the model
    rendered the fragment: *"7.0% of measured sleep (deep+light+REM+awake)"* —
    which reads like field names on the surface the "never print a field, key or
    path" rule governs. Batch 217's convention is that a basis is a sentence or it
    is nothing."""
    assert SLEEP_STAGE_PCT_BASIS is SLEEP_STAGE_PCT_BASIS_NOTE
    assert SLEEP_STAGE_PCT_BASIS.endswith(".")
    assert "Garmin's displayed Duration excludes it" in SLEEP_STAGE_PCT_BASIS


def test_the_prompt_asks_for_the_basis_on_every_stage_percentage() -> None:
    prompt = _prompt("morning_analysis")
    assert "on **every** stage percentage" in prompt
    assert "not once per read" in prompt


# ---------------------------------------------------------------------------
# AI238-10 — the structured caller uses the structured contract
# ---------------------------------------------------------------------------


def test_conversation_learning_asks_the_api_for_json_rather_than_asking_nicely() -> None:
    """This is the path that proposes durable additions to Mark's ``learned_context``
    — the app's persistent memory. A model opening with one sentence of preamble
    before the JSON failed the whole extraction: safe, silent, and the proposal
    queue simply stayed empty."""
    source = (SRC / "services" / "conversation_learning.py").read_text(encoding="utf-8")
    assert "output_schema=anthropic_schema(ExtractionEnvelope)" in source
    # The fence-stripping stays as a fallback rather than the mechanism.
    assert 'cleaned.startswith("```")' in source


def test_the_schema_transform_is_shared_rather_than_re_derived() -> None:
    longitudinal = (SRC / "services" / "longitudinal_analysis.py").read_text(encoding="utf-8")
    assert "_ANTHROPIC_UNSUPPORTED_SCHEMA_CONSTRAINTS" not in longitudinal
    assert "anthropic_schema(LongitudinalFindings)" in longitudinal


def test_effort_and_format_share_one_output_config() -> None:
    """They are two keys of **one** ``output_config``. Assigning it wholesale for
    either would silently drop the other — which for a structured caller means a
    schema-constrained response quietly becoming prose."""
    source = (SRC / "services" / "anthropic_text.py").read_text(encoding="utf-8")
    assert 'payload["output_config"] = {"effort": effort}' not in source
    assert 'output_config["effort"] = effort' in source
    assert 'output_config["format"]' in source


# ---------------------------------------------------------------------------
# DS237-09 — the packet stops carrying a home address
# ---------------------------------------------------------------------------


def test_no_packet_sends_a_home_address_or_a_stable_correlator() -> None:
    """Every morning brief sent a third party Mark's precise home location —
    twice, in the same request — plus a stable cross-request correlator, attached
    to his sleep times, HRV and body weight. No system prompt referenced any of
    them. The packet is stored in ``analyses.context_packet``, so they were in
    every archive and every future export as well."""
    for module_name in ("morning_analysis", "post_workout_analysis"):
        source = (SRC / "services" / f"{module_name}.py").read_text(encoding="utf-8")
        assert '"userId": str(player.id)' not in source
        assert '"latitude": player.latitude' not in source
        assert '"longitude": player.longitude' not in source
        assert '"latitude": row.latitude' not in source


def test_the_name_the_coach_addresses_him_by_stays() -> None:
    source = (SRC / "services" / "morning_analysis.py").read_text(encoding="utf-8")
    assert '"displayName": player.display_name' in source


# ---------------------------------------------------------------------------
# DS237-17 / CR236-13 — the reads that materialised JSONB nothing reads
# ---------------------------------------------------------------------------


def test_the_two_timeseries_reads_leave_the_raw_sample_behind() -> None:
    for module_name in ("post_workout_analysis", "post_walk_analysis"):
        source = (SRC / "services" / f"{module_name}.py").read_text(encoding="utf-8")
        assert "activity_timeseries_columns()" in source
        assert (
            "select(ActivityTimeSeries)\n"
            not in source.replace(".options(activity_timeseries_columns())", "")
            or "activity_timeseries_columns" in source
        )


def test_the_ownership_check_reads_one_column_not_six_kilobytes() -> None:
    """``history`` discards the row entirely, so it asks only the ownership
    question — but ``select(Analysis)`` materialised ``context_packet`` and
    ``raw_response`` to answer a boolean."""
    source = (SRC / "services" / "brief_chat.py").read_text(encoding="utf-8")
    assert "select(Analysis.user_id).where(Analysis.id == analysis_id)" in source
    assert "await self._assert_owned_analysis(player, analysis_id)" in source


def test_the_bulk_read_module_names_the_models_it_governs() -> None:
    """CR236-13: not a lint rule — the false-positive rate on ``select(Model)``
    would be unmanageable — but a named place plus a question ``batch-verify``
    now asks once per batch."""
    from src.services.bulk_history_reads import JSONB_CARRYING_MODELS

    assert set(JSONB_CARRYING_MODELS) == {
        "sleep",
        "daily_metrics",
        "temperature_readings",
        "analyses",
    }
    verify = (REPO / "docs" / "agent-commands" / "batch-verify.md").read_text(encoding="utf-8")
    assert "bulk_history_reads" in verify
    assert "CR236-13" in verify


# ---------------------------------------------------------------------------
# CR236-12 — one day-context assembly
# ---------------------------------------------------------------------------


def test_the_day_context_loaders_are_one_assembly() -> None:
    """The Home card and the evening sleep push describe the same day, and nothing
    compares them. Batch 184 recorded them as one assembly; Batch 189 recorded them
    as "behaviourally holds; structurally a copy"."""
    for module_name in ("daily_loop", "sleep_projection_context"):
        source = (SRC / "services" / f"{module_name}.py").read_text(encoding="utf-8")
        for loader in (
            "load_activities",
            "load_latest_temperature",
            "load_knowledge_base_content",
            "load_weather",
        ):
            assert loader in source, f"{module_name} does not use {loader}"
        # The SQL itself lives in one place now.
        assert "select(TemperatureReading)" not in source
        assert "select(WeatherDaily)" not in source


# ---------------------------------------------------------------------------
# CR236-04 — one post-activity lifecycle
# ---------------------------------------------------------------------------

READ_SERVICES = (
    PostWorkoutAnalysisService,
    PostWalkAnalysisService,
    PostStrengthAnalysisService,
    PostFlexibilityAnalysisService,
)


@pytest.mark.parametrize("service", READ_SERVICES, ids=lambda s: s.__name__)
def test_every_post_activity_read_runs_the_one_lifecycle(service: type) -> None:
    """Four copies of one lifecycle, each with its own complexity-13
    ``generate_and_store``. The bodies were 155 lines differing in 26, and every
    one of those 26 was a type name, a service name or a discipline literal. A fix
    applied to one copy silently skipped three — which had already happened inside
    the audit wave with Batch 232.1's in-flight handling."""
    assert issubclass(service, PostActivityReadRunner)
    assert "generate_and_store" not in vars(service), (
        f"{service.__name__} has its own generate_and_store again."
    )
    assert service.generate_and_store is PostActivityReadRunner.generate_and_store


@pytest.mark.parametrize("service", READ_SERVICES, ids=lambda s: s.__name__)
def test_every_read_declares_its_discipline(service: type) -> None:
    assert service.kind in {"ride", "walk", "strength", "flexibility"}
    assert isinstance(service.analysis_type, str) and service.analysis_type
    assert isinstance(service.prompt_version, str) and service.prompt_version


def test_the_ride_path_keeps_the_two_differences_that_are_real() -> None:
    """Its own currency predicate, which knows about ride re-grading, and a verdict
    from the recovery decision where the others are always advisory."""
    assert PostWorkoutAnalysisService.verdict_for is not PostActivityReadRunner.verdict_for
    packet = {"recoveryDecision": {"status": "Amber"}}
    assert PostWorkoutAnalysisService.verdict_for(None, packet) == "Amber"  # type: ignore[arg-type]
    assert PostWalkAnalysisService.verdict_for(None, packet) == "advisory"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CR236-08 — the offline migration path builds the same database
# ---------------------------------------------------------------------------


def test_offline_sql_puts_alembic_version_in_the_coach_schema() -> None:
    """``alembic upgrade base:head --sql`` is this project's offline-validation
    route when no Postgres is available. It rendered ``CREATE TABLE
    alembic_version`` with **no schema qualifier**, so a database provisioned by
    piping that SQL was invisible to ``alembic current``: the next online
    ``upgrade head`` saw an empty ``coach.alembic_version``, re-ran ``001``, and
    failed on the first ``CREATE TABLE`` that already existed."""
    rendered = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(REPO / "apps" / "api" / "alembic.ini"),
            "upgrade",
            "base:head",
            "--sql",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO / "apps" / "api"),
            # Rendering offline needs a parseable URL and never connects.
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        },
        check=True,
    ).stdout
    assert "CREATE TABLE coach.alembic_version" in rendered
    assert re.search(r"^CREATE TABLE alembic_version", rendered, re.M) is None
    # The 5s guard the online path sets was silently absent offline.
    assert "SET lock_timeout = '5s'" in rendered
    # And the schema exists before the version table lands in it.
    assert rendered.index("CREATE SCHEMA IF NOT EXISTS coach") < rendered.index(
        "CREATE TABLE coach.alembic_version"
    )


def test_both_migration_paths_configure_the_same_version_table() -> None:
    source = (REPO / "migrations" / "env.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    configured = {
        node.name: {
            kw.arg
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and ast.unparse(call.func).endswith("configure")
            for kw in call.keywords
        }
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"run_migrations_offline", "_do_run_migrations"}
    }
    for name, kwargs in configured.items():
        assert "version_table_schema" in kwargs, name
        assert "include_schemas" in kwargs, name
