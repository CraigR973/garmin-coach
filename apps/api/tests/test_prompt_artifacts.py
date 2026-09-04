"""Batch 253 (AI238-13): every PROMPT_VERSION has a declared regeneration contract.

Nineteen constants shared a name and behaved three different ways on a bump, and
nothing said which was which. The consequence has been observed twice — Batch 227
left Mark's Trends page blank on the surface his complaint came from, and Batch
230's close-out had to regenerate both trend buckets — and the stale case is live.
The guard was a checklist line in ``closeout.md``; these tests make the *inventory*
mechanical, and ``orphaned_artifacts`` makes the *check* executable.
"""

from __future__ import annotations

import ast
import re
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.services.prompt_artifacts import (
    PROMPT_ARTIFACTS,
    OrphanReport,
    RegenerationContract,
    orphaned_artifacts,
)

SERVICES = Path(__file__).parents[1] / "src" / "services"


def _modules_declaring_a_prompt_version() -> set[str]:
    """Discovered from the source, so a new constant cannot arrive undeclared."""
    found: set[str] = set()
    for path in SERVICES.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {
                    "PROMPT_VERSION",
                    "PROMPT_VERSION_BY_BUCKET",
                }:
                    found.add(path.stem)
    return found


def test_every_prompt_version_declares_what_a_bump_does() -> None:
    declared = {artifact.module for artifact in PROMPT_ARTIFACTS}
    discovered = _modules_declaring_a_prompt_version()
    assert discovered == declared, (
        "A PROMPT_VERSION without a declared regeneration contract. Add it to "
        "PROMPT_ARTIFACTS — undeclared is how Batch 227 blanked the Trends page."
    )


def test_each_contract_is_one_of_the_four_and_the_wrong_ones_carry_their_reason() -> None:
    for artifact in PROMPT_ARTIFACTS:
        assert isinstance(artifact.contract, RegenerationContract)
        if artifact.contract in {
            RegenerationContract.VERSION_FILTERED,
            RegenerationContract.UNFILTERED,
        }:
            assert artifact.note, (
                f"{artifact.module} does not self-heal, so its reason must be written "
                "down rather than rediscovered at the next close-out."
            )


def test_the_declared_self_healers_really_have_a_healing_mechanism() -> None:
    """A declaration is worth nothing if the code does not match it.

    Self-healing has three real forms in this codebase, and the test accepts all
    three: comparing the stored ``prompt_version`` directly; folding the version
    into the *generation identity* so a bump produces a new claim and the next run
    generates (``longitudinal_analysis``); or declaring ``prompt_version`` to
    ``PostActivityReadRunner``, which does the comparing (the four post-activity
    reads, since Batch 253's CR236-04 extraction).

    This test has twice caught a declaration drifting from the code: once when
    ``longitudinal_analysis`` was declared as "compares" and does not, and once
    when the post-activity mechanism moved into the shared runner.
    """
    for artifact in PROMPT_ARTIFACTS:
        if artifact.contract is not RegenerationContract.SELF_HEAL:
            continue
        source = (SERVICES / f"{artifact.module}.py").read_text(encoding="utf-8")
        compares = re.search(r"prompt_version\s*[=!]=\s*PROMPT_VERSION", source)
        identity = re.search(r"_generation_identity\((?:.|\n)*?prompt_version=", source)
        delegates = "PostActivityReadRunner" in source and re.search(
            r"^\s+prompt_version = PROMPT_VERSION$", source, re.M
        )
        assert compares or identity or delegates, (
            f"{artifact.module} is declared self-healing but has none of the three "
            "mechanisms: it neither compares prompt_version, nor carries it in its "
            "generation identity, nor declares it to PostActivityReadRunner."
        )


def test_the_version_filtered_read_really_filters() -> None:
    """The one contract whose bump silently empties a surface."""
    trends = next(a for a in PROMPT_ARTIFACTS if a.module == "trends")
    assert trends.contract is RegenerationContract.VERSION_FILTERED
    source = (SERVICES / "trends.py").read_text(encoding="utf-8")
    assert "Analysis.prompt_version == PROMPT_VERSION_BY_BUCKET[bucket]" in source


def test_declared_analysis_types_are_the_ones_the_module_writes() -> None:
    for artifact in PROMPT_ARTIFACTS:
        if not artifact.analysis_types:
            continue
        module = import_module(f"src.services.{artifact.module}")
        # ``insights`` names its type ``AUDIT_TYPE_DRIVERS``; the property is that
        # the string is a module-level constant, not what the constant is called.
        constants = {
            value
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str)
        }
        for analysis_type in artifact.analysis_types:
            assert analysis_type in constants, (
                f"{artifact.module} does not define {analysis_type!r} — the registry "
                "would silently count zero rows for it."
            )


def test_deterministic_modules_do_not_call_a_model() -> None:
    """The seven whose constant names a prompt that does not exist."""
    boundaries = {
        "generate_anthropic_text",
        "AnthropicReviewClient",
        "AnthropicMessageBatchClient",
    }
    for artifact in PROMPT_ARTIFACTS:
        if artifact.contract is not RegenerationContract.DETERMINISTIC:
            continue
        source = (SERVICES / f"{artifact.module}.py").read_text(encoding="utf-8")
        assert not (boundaries & set(re.findall(r"\w+", source))), (
            f"{artifact.module} is declared deterministic but calls a model."
        )


@pytest.mark.asyncio
async def test_the_orphan_check_reports_counts_rather_than_comparing_strings(
    db_conn: AsyncConnection,
) -> None:
    """Close-out's question, executable.

    Batch 250 reached the right answer by hand — drive the real lookup, do not
    compare version strings — and would have bought two unnecessary paid
    generations by doing it the other way. This is that discipline as code.
    """
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        reports = await orphaned_artifacts(session)

    assert reports, "the registry resolved no versioned artifacts at all"
    assert all(isinstance(report, OrphanReport) for report in reports)
    by_type = {report.analysis_type: report for report in reports}
    assert "morning" in by_type
    assert "seasonal_trend" in by_type
    for report in reports:
        # An empty database orphans nothing; the property under test is that the
        # report is derived from counts, not from a string comparison.
        assert report.orphaned >= 0 and report.current >= 0


def test_only_a_version_filtered_read_can_be_blanked() -> None:
    """The correction the first production run of this check earned.

    Against real data it reported **83 orphaned ``morning`` rows and none at the
    current version** — which looks alarming and means nothing, because the morning
    lookup does not filter on ``prompt_version``: 2026-09-03's brief still resolved
    at v43 under a v46 constant. A close-out trusting the raw count would have
    bought a paid regeneration for a surface that was never blank, which is the
    exact mistake this module exists to prevent.
    """
    orphaned_and_none_current = dict(orphaned=83, current=0, newest_orphaned_subject_date=None)

    self_healing = OrphanReport(
        module="morning_analysis",
        analysis_type="morning",
        contract=RegenerationContract.SELF_HEAL,
        current_version="morning-analysis-v46",
        **orphaned_and_none_current,
    )
    assert self_healing.blanks_a_surface is False
    assert self_healing.orphaned_rows_are_unreachable is False

    unfiltered = OrphanReport(
        module="reviews",
        analysis_type="monthly_review",
        contract=RegenerationContract.UNFILTERED,
        current_version="reviews-v7",
        **orphaned_and_none_current,
    )
    assert unfiltered.blanks_a_surface is False  # the old narrative is still served

    filtered = OrphanReport(
        module="trends",
        analysis_type="seasonal_trend",
        contract=RegenerationContract.VERSION_FILTERED,
        current_version="trends-month-v10",
        **orphaned_and_none_current,
    )
    assert filtered.blanks_a_surface is True
    assert filtered.orphaned_rows_are_unreachable is True

    replaced = OrphanReport(
        module="trends",
        analysis_type="seasonal_trend",
        contract=RegenerationContract.VERSION_FILTERED,
        current_version="trends-month-v10",
        orphaned=12,
        current=1,
        newest_orphaned_subject_date="2026-08-01",
    )
    assert replaced.blanks_a_surface is False  # something current replaces them
