"""What a ``PROMPT_VERSION`` bump does — declared, not remembered.

Batch 253 (AI238-13). Nineteen ``PROMPT_VERSION`` constants across ``src/services``
share a name and behave **three** different ways when one is bumped, and nothing
said which was which:

* **self-heal** — the read is regenerated on a version mismatch. Correct.
* **version-filtered** — the lookup filters on the current version, so every
  stored artifact at the old version becomes unreachable and the surface renders
  blank until someone regenerates it.
* **unfiltered** — the lookup ignores the version, so an old-prompt narrative is
  served as current.

Both of the wrong ones have been observed. Batch 230's close-out found both trend
buckets blank after a bump and had to regenerate them twice; Batch 227 left Mark's
Trends page empty on the surface his original complaint came from. And the stale
case is live: the only ``monthly_review`` in the database was generated
2026-07-05 on ``reviews-v3-2026-07-05`` while the code is on ``reviews-v7``.

Seven more constants sit on **deterministic, non-model paths** where the name
implies an LLM prompt that does not exist. They are declared here too, because the
useful property is that *every* constant has a stated contract, not that the
model-calling ones do.

The guard used to be a checklist line in ``closeout.md``. It is now
:func:`orphaned_artifacts`, which drives the real lookups against the real
database and reports what a bump actually withdrew — the discipline Batch 250
arrived at by hand, executable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis


class RegenerationContract(StrEnum):
    """What happens to a stored artifact when its prompt version moves."""

    #: The generator compares the stored version and regenerates on a mismatch,
    #: so a bump costs one generation and nothing goes missing.
    SELF_HEAL = "self_heal"
    #: The **read** filters on the current version, so a bump makes every stored
    #: artifact unreachable. A bump here needs a deliberate regeneration decision.
    VERSION_FILTERED = "version_filtered"
    #: The read ignores the version, so a bump withdraws nothing — and an
    #: old-prompt artifact keeps being served as current.
    UNFILTERED = "unfiltered"
    #: Not a model prompt at all. The constant versions a deterministic rule set,
    #: and the name is historical.
    DETERMINISTIC = "deterministic"


@dataclass(frozen=True, slots=True)
class PromptArtifact:
    module: str
    contract: RegenerationContract
    #: ``analysis_type`` values this module writes, for the orphan check. Empty
    #: for deterministic modules and for modules that write no ``Analysis`` row.
    analysis_types: tuple[str, ...] = ()
    note: str = ""


#: Every ``PROMPT_VERSION`` in ``src/services``, with what its bump does.
#: ``test_prompt_artifacts`` fails if a constant appears without a declaration.
PROMPT_ARTIFACTS: tuple[PromptArtifact, ...] = (
    PromptArtifact(
        "morning_analysis",
        RegenerationContract.SELF_HEAL,
        ("morning",),
        "generate_and_store compares the stored version inside the generation claim.",
    ),
    PromptArtifact("post_workout_analysis", RegenerationContract.SELF_HEAL, ("post_workout",)),
    PromptArtifact("post_walk_analysis", RegenerationContract.SELF_HEAL, ("post_walk",)),
    PromptArtifact("post_strength_analysis", RegenerationContract.SELF_HEAL, ("post_strength",)),
    PromptArtifact(
        "post_flexibility_analysis", RegenerationContract.SELF_HEAL, ("post_flexibility",)
    ),
    PromptArtifact("insights", RegenerationContract.SELF_HEAL, ("driver_correlation",)),
    PromptArtifact(
        "trends",
        RegenerationContract.VERSION_FILTERED,
        ("seasonal_trend",),
        "The read filters on PROMPT_VERSION_BY_BUCKET, so a bump blanks the page. "
        "Kept filtered deliberately (Batch 253): self-healing it would spend a paid "
        "generation on a page open. orphaned_artifacts() is the guard instead.",
    ),
    PromptArtifact(
        "reviews",
        RegenerationContract.UNFILTERED,
        ("weekly_review", "monthly_review"),
        "The read does not filter, so an old-prompt narrative is served as current. "
        "Live now: the only monthly_review was generated on reviews-v3.",
    ),
    PromptArtifact(
        "brief_chat",
        RegenerationContract.UNFILTERED,
        (),
        "Chat turns are a conversation, not a regenerable artifact — a past answer "
        "stays what was said.",
    ),
    PromptArtifact(
        "handover",
        RegenerationContract.UNFILTERED,
        ("handover_export",),
        "Generated on demand; the stored copy is a record of what was handed over.",
    ),
    PromptArtifact(
        "longitudinal_analysis",
        RegenerationContract.SELF_HEAL,
        ("longitudinal_findings",),
        "Monthly submission is idempotent per month and re-submits on a version change.",
    ),
    PromptArtifact(
        "conversation_learning",
        RegenerationContract.UNFILTERED,
        (),
        "Writes learned-context candidates, not a rendered artifact.",
    ),
    # -- deterministic: no model, no prompt, historical name --------------------
    PromptArtifact("executable_coaching", RegenerationContract.DETERMINISTIC),
    PromptArtifact("nudge_alerts", RegenerationContract.DETERMINISTIC),
    PromptArtifact("experiment_tracker", RegenerationContract.DETERMINISTIC),
    PromptArtifact("experiment_loop", RegenerationContract.DETERMINISTIC),
    PromptArtifact("experiment_evaluation", RegenerationContract.DETERMINISTIC),
    PromptArtifact("state_change_coach", RegenerationContract.DETERMINISTIC),
    PromptArtifact("weekly_restructure", RegenerationContract.DETERMINISTIC),
)


@dataclass(frozen=True, slots=True)
class OrphanReport:
    module: str
    analysis_type: str
    contract: RegenerationContract
    current_version: str
    #: Rows stored at a version other than the current one.
    orphaned: int
    #: Rows stored at the current version.
    current: int
    newest_orphaned_subject_date: str | None

    @property
    def blanks_a_surface(self) -> bool:
        """Would a reader of this artifact find nothing?

        **Only a version-filtered read can be blanked**, and the first production
        run of this check proved why that has to be stated here rather than left
        to whoever reads the output. Against real data it reported 83 orphaned
        ``morning`` rows with none at the current version — which looks alarming
        and means nothing: the morning lookup does not filter on
        ``prompt_version``, so 2026-09-03's brief still resolves at v43 under a v46
        constant. A close-out that trusted the raw count would have bought a paid
        regeneration to fix a surface that was never blank, which is the exact
        mistake this module exists to prevent (Batch 227, Batch 250).
        """
        if self.contract is not RegenerationContract.VERSION_FILTERED:
            return False
        return self.orphaned > 0 and self.current == 0

    @property
    def orphaned_rows_are_unreachable(self) -> bool:
        """Are the orphaned rows themselves beyond reach, blank surface or not?

        True for a version-filtered read. For the other contracts the rows are
        still served (``unfiltered``) or replaced on the next run (``self_heal``).
        """
        return (
            self.contract is RegenerationContract.VERSION_FILTERED and self.orphaned > 0
        )


def _current_versions() -> dict[str, dict[str, str]]:
    """``{module: {analysis_type: version}}`` resolved from the live constants."""
    from importlib import import_module

    resolved: dict[str, dict[str, str]] = {}
    for artifact in PROMPT_ARTIFACTS:
        if artifact.contract is RegenerationContract.DETERMINISTIC or not artifact.analysis_types:
            continue
        module = import_module(f"src.services.{artifact.module}")
        by_bucket = getattr(module, "PROMPT_VERSION_BY_BUCKET", None)
        version = getattr(module, "PROMPT_VERSION", None)
        for analysis_type in artifact.analysis_types:
            if isinstance(by_bucket, dict):
                # One module, several artifacts, several versions (trends).
                resolved.setdefault(artifact.module, {})[analysis_type] = str(
                    next(iter(by_bucket.values()))
                )
            elif isinstance(version, str):
                resolved.setdefault(artifact.module, {})[analysis_type] = version
    return resolved


async def orphaned_artifacts(
    session: AsyncSession, *, user_id: uuid.UUID | None = None
) -> list[OrphanReport]:
    """What each declared artifact's current prompt version leaves unreachable.

    Drives the real counts rather than comparing version strings in the abstract:
    a bump that orphans rows nothing serves costs nothing, and a bump that empties
    a surface is the one worth a paid regeneration. ``blanks_a_surface`` is the
    property close-out actually asks about.
    """
    reports: list[OrphanReport] = []
    contracts = {artifact.module: artifact.contract for artifact in PROMPT_ARTIFACTS}
    for module, versions in _current_versions().items():
        for analysis_type, version in versions.items():
            where = [Analysis.analysis_type == analysis_type]
            if user_id is not None:
                where.append(Analysis.user_id == user_id)
            current = await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(*where, Analysis.prompt_version == version)
            )
            orphaned = await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(*where, Analysis.prompt_version != version)
            )
            newest = await session.scalar(
                select(func.max(Analysis.subject_date)).where(
                    *where, Analysis.prompt_version != version
                )
            )
            reports.append(
                OrphanReport(
                    module=module,
                    analysis_type=analysis_type,
                    contract=contracts[module],
                    current_version=version,
                    orphaned=int(orphaned or 0),
                    current=int(current or 0),
                    newest_orphaned_subject_date=newest.isoformat() if newest else None,
                )
            )
    return reports
