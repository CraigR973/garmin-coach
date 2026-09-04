"""One post-activity read lifecycle, four disciplines (Batch 253, CR236-04).

``post_workout_analysis``, ``post_walk_analysis``, ``post_flexibility_analysis``
and ``post_strength_analysis`` were four copies of one lifecycle — pending
selector → packet → thin Anthropic boundary → ``claim_generation_request`` →
``Analysis`` row → status write — each with its own ``generate_and_store`` at
cyclomatic complexity 13. Measured pairwise, flexibility and strength were 78%
identical line-for-line; their ``generate_and_store`` bodies were **155 lines
each differing in 26**, and every one of those 26 was a type name, a service name
or the literal ``"strength"`` / ``"walk"``.

A fix applied to one copy silently skipped three, and that had already happened
inside the audit wave: Batch 232.1's ``GenerationRequestInProgress`` handling
reached ``post_workout_analysis`` and the router's ride path, and the other three
readers inherited it only indirectly.

The abstraction this extends already existed and was already trusted:
``post_activity_analysis`` unified kind selection and ``post_activity_state``
unified the status lifecycle. This is the same seam one step further. Each service
keeps its packet builder and its prompt — which is where the real per-discipline
content lives — and declares the handful of things that genuinely differ.

**Three of the differences are real and are hooks rather than constants**, which
the four copies had obscured: the ride path uses its own currency predicate
(``_analysis_is_current``, which knows about ride re-grading) where the others ask
whether the read covers the check-in, and it derives its ``verdict`` from
``recoveryDecision.status`` where the others are always ``"advisory"``.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, Analysis, ManualEntry
from src.models.profile import Profile
from src.services.activity_dates import activity_local_date
from src.services.generation_requests import (
    claim_generation_request,
    manual_entry_generation_version,
    post_activity_generation_identity,
    stamp_generation_identity,
)
from src.services.post_activity_state import (
    PostActivityKind,
    mark_post_activity_generation,
    prepare_post_activity_generation,
)
from src.services.workload_budget import workload_slot


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PostActivityGeneration(Protocol):
    """What every discipline's Anthropic client returns.

    Read-only members on purpose: the four concrete ``ClaudeGenerationResult``
    dataclasses are frozen, and a Protocol with settable attributes would demand
    invariance they cannot supply.
    """

    @property
    def output_markdown(self) -> str: ...

    @property
    def raw_response(self) -> dict[str, Any]: ...

    @property
    def model_name(self) -> str | None: ...


class PostActivityClient(Protocol):
    async def generate(
        self, *, context_packet: dict[str, Any], user_prompt: str
    ) -> PostActivityGeneration: ...


class PostActivityReadRunner[ResultT](ABC):
    """The lifecycle. Subclasses supply the discipline."""

    session: AsyncSession

    #: The value ``post_activity_state`` keys its status rows on.
    kind: PostActivityKind
    #: The ``Analysis.analysis_type`` this read writes.
    analysis_type: str
    #: The prompt version this read is generated at.
    prompt_version: str

    # -- the discipline ------------------------------------------------------

    @abstractmethod
    async def assemble_packet(self, player: Profile, activity: Activity) -> dict[str, Any]: ...

    @abstractmethod
    def build_user_prompt(self, context_packet: dict[str, Any]) -> str: ...

    @abstractmethod
    def default_client(self) -> PostActivityClient: ...

    @abstractmethod
    def make_result(self, analysis: Analysis, *, generated: bool) -> ResultT: ...

    @abstractmethod
    async def latest_analysis_for_activity(self, activity_id: uuid.UUID) -> Analysis | None: ...

    @abstractmethod
    async def activity_checkin(
        self, user_id: uuid.UUID, activity_id: uuid.UUID
    ) -> ManualEntry | None: ...

    @abstractmethod
    def analysis_is_current(self, analysis: Analysis, checkin: ManualEntry | None) -> bool:
        """Is a stored read still the right answer for this check-in?

        The ride path answers this differently from the other three, which is why
        it is a hook rather than a shared helper.
        """

    @abstractmethod
    def failure_reason(self, exc: Exception) -> str: ...

    def verdict_for(self, context_packet: dict[str, Any]) -> str | None:
        """The ``Analysis.verdict`` this read records.

        ``"advisory"`` for three of the four; the ride path overrides it with its
        recovery decision.
        """
        return "advisory"

    # -- the lifecycle -------------------------------------------------------

    async def generate_and_store(
        self,
        player: Profile,
        activity: Activity,
        *,
        client: PostActivityClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> ResultT:
        subject_date = activity_local_date(activity, player.timezone)
        checkin = await self.activity_checkin(player.id, activity.id)
        input_version = manual_entry_generation_version(checkin)
        request_identity = post_activity_generation_identity(
            user_id=player.id,
            activity_id=activity.id,
            input_version=input_version,
            prompt_version=self.prompt_version,
        )
        # Persist Batch 159's honest ``generating`` state before taking the
        # transaction-scoped paid-work lock. No commit occurs after the claim
        # until the completed/failed request state is ready.
        matched_workout_id = await prepare_post_activity_generation(
            self.session,
            user_id=player.id,
            activity_id=activity.id,
            subject_date=subject_date,
            kind=self.kind,
            commit=False,
        )
        if commit:
            await self.session.commit()
        async with claim_generation_request(
            self.session,
            user_id=player.id,
            request_identity=request_identity,
            generation_kind=self.analysis_type,
            lease_scope=f"post:{player.id}:{activity.id}",
        ) as claim:
            existing: Analysis | None = claim.existing_analysis
            if existing is not None:
                packet = existing.context_packet
                if not (
                    existing.prompt_version == self.prompt_version
                    and isinstance(packet, dict)
                    and packet.get("generationIdentity") == request_identity
                ):
                    claim.restart()
                    existing = None
            if existing is not None:
                return await self._reuse(
                    existing,
                    player=player,
                    activity=activity,
                    subject_date=subject_date,
                    matched_workout_id=matched_workout_id,
                    commit=commit,
                )

            if not force:
                latest = await self.latest_analysis_for_activity(activity.id)
                if latest is not None and self.analysis_is_current(latest, checkin):
                    claim.mark_completed(latest)
                    return await self._reuse(
                        latest,
                        player=player,
                        activity=activity,
                        subject_date=subject_date,
                        matched_workout_id=matched_workout_id,
                        commit=commit,
                    )

            try:
                context_packet = await self.assemble_packet(player, activity)
                stamp_generation_identity(
                    context_packet,
                    request_identity=request_identity,
                    input_version=input_version,
                )
                user_prompt = self.build_user_prompt(context_packet)
                analysis_client = client or self.default_client()
                async with workload_slot(workload="anthropic", user_id=player.id):
                    generation = await analysis_client.generate(
                        context_packet=context_packet,
                        user_prompt=user_prompt,
                    )
            except Exception as exc:
                reason = self.failure_reason(exc)
                claim.mark_failed(reason)
                await mark_post_activity_generation(
                    self.session,
                    user_id=player.id,
                    activity_id=activity.id,
                    planned_workout_id=matched_workout_id,
                    subject_date=subject_date,
                    kind=self.kind,
                    status="failed",
                    reason=reason,
                    commit=commit,
                )
                raise

            analysis = Analysis(
                user_id=player.id,
                activity_id=activity.id,
                planned_workout_id=matched_workout_id,
                analysis_type=self.analysis_type,
                subject_date=subject_date,
                generated_at_utc=_utcnow(),
                prompt_version=self.prompt_version,
                model_name=generation.model_name,
                verdict=self.verdict_for(context_packet),
                context_packet=context_packet,
                output_markdown=generation.output_markdown,
                raw_response=generation.raw_response,
            )
            self.session.add(analysis)
            await self.session.flush()
            claim.mark_completed(analysis)
            await mark_post_activity_generation(
                self.session,
                user_id=player.id,
                activity_id=activity.id,
                planned_workout_id=matched_workout_id,
                subject_date=subject_date,
                kind=self.kind,
                status="ready",
                commit=False,
            )
            if commit:
                await self.session.commit()
                await self.session.refresh(analysis)
            else:
                await self.session.flush()
            return self.make_result(analysis, generated=True)

    async def _reuse(
        self,
        analysis: Analysis,
        *,
        player: Profile,
        activity: Activity,
        subject_date: Any,
        matched_workout_id: uuid.UUID | None,
        commit: bool,
    ) -> ResultT:
        """Serve a stored read, re-pointing it at a workout matched since."""
        if matched_workout_id is not None and analysis.planned_workout_id != matched_workout_id:
            analysis.planned_workout_id = matched_workout_id
        await mark_post_activity_generation(
            self.session,
            user_id=player.id,
            activity_id=activity.id,
            planned_workout_id=matched_workout_id,
            subject_date=subject_date,
            kind=self.kind,
            status="ready",
            commit=False,
        )
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        else:
            await self.session.flush()
        return self.make_result(analysis, generated=False)
