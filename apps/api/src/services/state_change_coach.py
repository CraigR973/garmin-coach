"""Coach-initiated messages for meaningful state transitions (Batch 187)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, BriefMessage, Experiment
from src.models.profile import Profile
from src.services.brief_chat import ROLE_ASSISTANT
from src.services.chronic_patterns import ChronicPatternSuggestionService
from src.services.experiment_evaluation import (
    AUDIT_TYPE_EVALUATION,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    ExperimentEvaluationService,
)
from src.services.experiment_tracker import STATUS_ACTIVE
from src.services.insights import OUTCOME_SLEEP_SCORE, InsightsService
from src.services.weekly_mix import WeeklyMixService

ANALYSIS_TYPE_STATE_CHANGE = "state_change_coach"
PROMPT_VERSION = "state-change-coach:v1-2026-08-05"
ORIGIN_KIND_STATE_CHANGE = "state_change"
BUDGET_WINDOW_DAYS = 7

TransitionKind = Literal["chronic_action", "experiment_outcome", "weekly_mix"]

_RANK: dict[TransitionKind, int] = {
    "chronic_action": 0,
    "experiment_outcome": 1,
    "weekly_mix": 2,
}


@dataclass(frozen=True)
class StateSnapshot:
    kind: TransitionKind
    state_key: str
    state_value: str
    title: str
    message: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class StateChangeCandidate:
    snapshot: StateSnapshot
    previous_value: str | None


@dataclass(frozen=True)
class StateChangeResult:
    message: BriefMessage | None
    analysis: Analysis | None
    message_created: bool
    reason: str
    candidates_seen: int = 0


def transition_candidate(
    current: StateSnapshot | None,
    previous_value: str | None,
) -> StateChangeCandidate | None:
    if current is None:
        return None
    if previous_value == current.state_value:
        return None
    return StateChangeCandidate(snapshot=current, previous_value=previous_value)


def choose_ranked_candidate(
    candidates: list[StateChangeCandidate],
) -> StateChangeCandidate | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (_RANK[item.snapshot.kind], item.snapshot.state_key),
    )[0]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _aware_utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _packet_value(packet: dict[str, Any], *path: str) -> Any:
    node: Any = packet
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _chronic_snapshot_from_packet(packet: dict[str, Any]) -> StateSnapshot | None:
    action = _packet_value(packet, "verdict", "chronicAction")
    if not isinstance(action, dict) or action.get("triggered") is not True:
        return None
    return _chronic_snapshot(action)


def _chronic_snapshot(action: dict[str, Any]) -> StateSnapshot | None:
    if action.get("triggered") is not True or action.get("suppressedByPlan") is True:
        return None
    kind = str(action.get("kind") or "deload_proposal")
    sources = [str(item) for item in action.get("triggerSources", []) if item]
    state_value = ":".join([kind, *sources]) if sources else kind
    reason = next(
        (str(item) for item in action.get("reasons", []) if isinstance(item, str) and item),
        "The longer-term recovery signal has changed.",
    )
    if kind == "rearrange_proposal":
        title = "A short recovery pattern has appeared"
        message = (
            "**Something changed:** the recent Red-morning pattern now looks worth "
            f"rearranging rather than ignoring. {reason} I have not changed the plan; "
            "this is a prompt to look at the week and use the existing apply step if it fits."
        )
    else:
        title = "A sustained recovery pattern has appeared"
        message = (
            "**Something changed:** the longer-term recovery markers now meet the "
            f"threshold for a deload proposal. {reason} I have not changed any workout; "
            "any plan change still needs explicit approval."
        )
    return StateSnapshot(
        kind="chronic_action",
        state_key="chronic_action",
        state_value=state_value,
        title=title,
        message=message,
        evidence=action,
    )


def _weekly_mix_snapshots_from_packet(packet: dict[str, Any]) -> list[StateSnapshot]:
    mix = _packet_value(packet, "verdict", "weeklyMix")
    if not isinstance(mix, dict):
        return []
    return _weekly_mix_snapshots(mix)


def _weekly_mix_snapshots(mix_packet: dict[str, Any]) -> list[StateSnapshot]:
    snapshots: list[StateSnapshot] = []
    for raw in mix_packet.get("buckets", []):
        if not isinstance(raw, dict) or raw.get("atRisk") is not True:
            continue
        bucket = str(raw.get("bucket") or "")
        if not bucket:
            continue
        label = str(raw.get("label") or bucket)
        due = raw.get("due")
        remaining = raw.get("remainingPlanned")
        snapshots.append(
            StateSnapshot(
                kind="weekly_mix",
                state_key=f"weekly_mix:{bucket}",
                state_value="at_risk",
                title=f"{label} has gone at risk",
                message=(
                    f"**Something changed:** {label} has quietly gone at risk this week "
                    f"({due} still due, {remaining} still scheduled). I have not moved "
                    "anything; this is a heads-up while there is still time to choose a fix."
                ),
                evidence=raw,
            )
        )
    return snapshots


def _experiment_snapshot(experiment: Experiment, packet: dict[str, Any]) -> StateSnapshot | None:
    recommendation = packet.get("recommendation")
    if recommendation not in {RECOMMEND_SUPPORTED, RECOMMEND_REFUTED}:
        return None
    status = packet.get("status")
    if status != "ok":
        return None
    reasons = packet.get("reasons")
    reason = (
        next((str(item) for item in reasons if isinstance(item, str) and item), "")
        if isinstance(reasons, list)
        else ""
    )
    recommendation_text = "supported" if recommendation == RECOMMEND_SUPPORTED else "refuted"
    message = (
        f"**Something changed:** {experiment.title} now has enough evidence to read as "
        f"{recommendation_text}. {reason} I have not concluded it for you; the experiment "
        "still needs your explicit decision."
    ).strip()
    return StateSnapshot(
        kind="experiment_outcome",
        state_key=f"experiment:{experiment.id}",
        state_value=str(recommendation),
        title=f"{experiment.title} outcome ready",
        message=message,
        evidence=packet,
    )


class StateChangeCoachService:
    """Detect one meaningful transition and deliver it into the coach thread."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        player: Profile,
        *,
        as_of: date,
        now_utc: datetime | None = None,
        commit: bool = True,
    ) -> StateChangeResult:
        sent_at = _aware_utc(now_utc)
        if await self._budget_spent(player, as_of=as_of):
            return StateChangeResult(
                message=None,
                analysis=None,
                message_created=False,
                reason="budget_spent",
            )

        candidates = await self._candidates(player, as_of=as_of)
        chosen = choose_ranked_candidate(candidates)
        if chosen is None:
            if commit:
                await self.session.commit()
            return StateChangeResult(
                message=None,
                analysis=None,
                message_created=False,
                reason="no_transition",
                candidates_seen=len(candidates),
            )

        existing = await self._existing_analysis(
            player,
            as_of=as_of,
            state_key=chosen.snapshot.state_key,
            state_value=chosen.snapshot.state_value,
        )
        if existing is not None:
            message = await self._message_for_analysis(player, existing)
            return StateChangeResult(
                message=message,
                analysis=existing,
                message_created=False,
                reason="already_delivered",
                candidates_seen=len(candidates),
            )

        packet = {
            "subjectDate": as_of.isoformat(),
            "transitionKind": chosen.snapshot.kind,
            "stateKey": chosen.snapshot.state_key,
            "stateValue": chosen.snapshot.state_value,
            "previousValue": chosen.previous_value,
            "title": chosen.snapshot.title,
            "evidence": chosen.snapshot.evidence,
            "budgetWindowDays": BUDGET_WINDOW_DAYS,
            "delivery": "coach_thread",
            "verdictImpact": "none",
            "planMutation": "none",
        }
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
            analysis_type=ANALYSIS_TYPE_STATE_CHANGE,
            subject_date=as_of,
            generated_at_utc=sent_at.replace(tzinfo=None),
            prompt_version=PROMPT_VERSION,
            model_name=None,
            verdict=None,
            context_packet=packet,
            output_markdown=chosen.snapshot.message,
            raw_response={},
        )
        self.session.add(analysis)
        await self.session.flush()
        message = BriefMessage(
            user_id=player.id,
            analysis_id=analysis.id,
            origin_kind=ORIGIN_KIND_STATE_CHANGE,
            origin_date=as_of,
            role=ROLE_ASSISTANT,
            content=chosen.snapshot.message,
            created_utc=sent_at.replace(tzinfo=None),
        )
        self.session.add(message)
        await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
            await self.session.refresh(message)
        return StateChangeResult(
            message=message,
            analysis=analysis,
            message_created=True,
            reason="delivered",
            candidates_seen=len(candidates),
        )

    async def _candidates(self, player: Profile, *, as_of: date) -> list[StateChangeCandidate]:
        previous_morning = await self._previous_morning(player, as_of=as_of)
        previous_packet = (
            previous_morning.context_packet
            if previous_morning is not None and isinstance(previous_morning.context_packet, dict)
            else {}
        )
        candidates: list[StateChangeCandidate] = []

        chronic = await self._current_chronic(player, as_of=as_of)
        previous_chronic = _chronic_snapshot_from_packet(previous_packet)
        candidate = transition_candidate(
            chronic,
            previous_chronic.state_value if previous_chronic is not None else None,
        )
        if candidate is not None:
            candidates.append(candidate)

        previous_mix = {
            snapshot.state_key: snapshot.state_value
            for snapshot in _weekly_mix_snapshots_from_packet(previous_packet)
        }
        for snapshot in await self._current_weekly_mix(player, as_of=as_of):
            candidate = transition_candidate(snapshot, previous_mix.get(snapshot.state_key))
            if candidate is not None:
                candidates.append(candidate)

        candidates.extend(await self._experiment_candidates(player, as_of=as_of))
        return candidates

    async def _current_chronic(self, player: Profile, *, as_of: date) -> StateSnapshot | None:
        drivers = await InsightsService(self.session).cached_drivers(player, as_of=as_of)
        result = await ChronicPatternSuggestionService(self.session).suggestions(
            player,
            as_of=as_of,
            sleep_drivers=drivers.outcomes.get(OUTCOME_SLEEP_SCORE, []),
        )
        return _chronic_snapshot(result.action_signal.to_packet())

    async def _current_weekly_mix(self, player: Profile, *, as_of: date) -> list[StateSnapshot]:
        if as_of.weekday() >= 6:
            return []
        mix = await WeeklyMixService(self.session).summarize_for_verdict(
            player,
            as_of,
            verdict_status="Green",
            swap=None,
        )
        return _weekly_mix_snapshots(mix.to_packet())

    async def _experiment_candidates(
        self, player: Profile, *, as_of: date
    ) -> list[StateChangeCandidate]:
        experiments = (
            (
                await self.session.execute(
                    select(Experiment)
                    .where(Experiment.user_id == player.id, Experiment.status == STATUS_ACTIVE)
                    .order_by(Experiment.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        service = ExperimentEvaluationService(self.session)
        candidates: list[StateChangeCandidate] = []
        for experiment in experiments:
            previous = await self._previous_experiment_evaluation(
                player,
                experiment_id=experiment.id,
                before=as_of,
            )
            previous_value = None
            if previous is not None and isinstance(previous.context_packet, dict):
                previous_snapshot = _experiment_snapshot(experiment, previous.context_packet)
                previous_value = previous_snapshot.state_value if previous_snapshot else None
            _result, analysis = await service.run(
                player,
                experiment.id,
                as_of=as_of,
                commit=False,
            )
            snapshot = (
                _experiment_snapshot(experiment, analysis.context_packet)
                if isinstance(analysis.context_packet, dict)
                else None
            )
            candidate = transition_candidate(snapshot, previous_value)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _previous_morning(self, player: Profile, *, as_of: date) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == "morning",
                    Analysis.subject_date < as_of,
                )
                .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                .limit(1)
            ),
        )

    async def _previous_experiment_evaluation(
        self,
        player: Profile,
        *,
        experiment_id: Any,
        before: date,
    ) -> Analysis | None:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
                        Analysis.subject_date < before,
                    )
                    .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                )
            )
            .scalars()
            .all()
        )
        target = str(experiment_id)
        for row in rows:
            packet = row.context_packet
            if isinstance(packet, dict) and packet.get("experimentId") == target:
                return row
        return None

    async def _budget_spent(self, player: Profile, *, as_of: date) -> bool:
        start = as_of - timedelta(days=BUDGET_WINDOW_DAYS - 1)
        row = await self.session.scalar(
            select(Analysis.id)
            .where(
                Analysis.user_id == player.id,
                Analysis.analysis_type == ANALYSIS_TYPE_STATE_CHANGE,
                Analysis.subject_date >= start,
                Analysis.subject_date <= as_of,
            )
            .limit(1)
        )
        return row is not None

    async def _existing_analysis(
        self,
        player: Profile,
        *,
        as_of: date,
        state_key: str,
        state_value: str,
    ) -> Analysis | None:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == ANALYSIS_TYPE_STATE_CHANGE,
                        Analysis.subject_date == as_of,
                    )
                    .order_by(desc(Analysis.generated_at_utc))
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            packet = row.context_packet
            if (
                isinstance(packet, dict)
                and packet.get("stateKey") == state_key
                and packet.get("stateValue") == state_value
            ):
                return row
        return None

    async def _message_for_analysis(
        self, player: Profile, analysis: Analysis
    ) -> BriefMessage | None:
        return cast(
            BriefMessage | None,
            await self.session.scalar(
                select(BriefMessage)
                .where(
                    BriefMessage.user_id == player.id,
                    BriefMessage.analysis_id == analysis.id,
                    BriefMessage.role == ROLE_ASSISTANT,
                )
                .limit(1)
            ),
        )
