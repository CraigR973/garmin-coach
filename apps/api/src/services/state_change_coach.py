"""Coach-initiated messages for meaningful state transitions (Batch 187)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, BriefMessage, Experiment
from src.models.profile import Profile
from src.services.brief_chat import ROLE_ASSISTANT
from src.services.chronic_patterns import driver_label
from src.services.experiment_evaluation import (
    AUDIT_TYPE_EVALUATION,
    KIND_CORRELATION,
    KIND_GATE,
    KIND_GROUP_COMPARE,
    KIND_INTERVENTION_COMPARE,
    RECOMMEND_REFUTED,
    RECOMMEND_SUPPORTED,
    ExperimentEvaluationService,
    evaluation_packet,
)
from src.services.experiment_tracker import STATUS_ACTIVE
from src.services.weekly_mix import WeeklyMixService

ANALYSIS_TYPE_STATE_CHANGE = "state_change_coach"
PROMPT_VERSION = "state-change-coach:v2-2026-08-15"
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


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    spend_type: Literal["initial", "preemption"] | None = None
    preempted_analysis_id: uuid.UUID | None = None


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


def _state_change_lock_key(user_id: uuid.UUID, as_of: date) -> int:
    """Stable PostgreSQL advisory-lock key for one state-change artifact."""
    digest = hashlib.sha256(f"state-change:{user_id}:{as_of.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


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
            "**Something changed:** the recent pattern of still-recovering mornings now looks "
            f"worth rearranging rather than ignoring. {reason} I have not changed the plan; "
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


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def plain_outcome_sentence(packet: dict[str, Any]) -> str:
    """What an experiment's evidence says, in words Mark can read (Batch 382).

    The evaluation's own first reason is for the Experiments page and Craig: it quotes
    ``r=+0.10``, a range and a driver's key. The 4 Nov notice sent it to Mark as it stood.
    This builds a sentence from the same evidence, or returns nothing when a figure it needs
    is missing, so a notice never falls back to the technical line.
    """

    recommendation = packet.get("recommendation")
    evidence = packet.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    kind = packet.get("kind")
    if kind == KIND_CORRELATION:
        driver = evidence.get("strongestDriver")
        if recommendation == RECOMMEND_SUPPORTED and isinstance(driver, str) and driver:
            label = driver_label(driver)
            return (
                f"{label[:1].upper()}{label[1:]} moves closely with the disturbed nights, "
                "so it looks like a trigger."
            )
        if recommendation == RECOMMEND_REFUTED:
            return (
                "Nothing I can measure lines up closely enough with the disturbed nights "
                "to be a trigger."
            )
    if kind == KIND_GATE and recommendation == RECOMMEND_SUPPORTED:
        streak, nights, floor = (
            _number(evidence.get("currentStreak")),
            _number(evidence.get("gateNights")),
            _number(evidence.get("floor")),
        )
        if streak is not None and nights is not None and floor is not None:
            return (
                f"Your age-adjusted sleep score has stayed at or above {floor:g} for "
                f"{streak:g} nights in a row, which meets the {nights:g}-night target."
            )
    if kind == KIND_INTERVENTION_COMPARE:
        rem, awake = _number(evidence.get("remPctDelta")), _number(evidence.get("awakeMinDelta"))
        if rem is not None and awake is not None:
            return (
                f"On the nights you tried it, REM was {abs(rem):.1f} percentage points "
                f"{'higher' if rem >= 0 else 'lower'} and you were awake {abs(awake):.0f} minutes "
                f"{'longer' if awake >= 0 else 'less'} than on the nights you didn't."
            )
    if kind == KIND_GROUP_COMPARE:
        metric = evidence.get("metricLabel")
        recovery, build = _number(evidence.get("recoveryMean")), _number(evidence.get("buildMean"))
        units = evidence.get("units")
        if isinstance(metric, str) and metric and recovery is not None and build is not None:
            unit = f" {units}" if isinstance(units, str) and units else ""
            name = metric if metric[:2].isupper() else metric.lower()
            return (
                f"Your {name} averaged {recovery:g}{unit} in recovery weeks against "
                f"{build:g}{unit} in build weeks."
            )
    return ""


def _experiment_snapshot(experiment: Experiment, packet: dict[str, Any]) -> StateSnapshot | None:
    recommendation = packet.get("recommendation")
    if recommendation not in {RECOMMEND_SUPPORTED, RECOMMEND_REFUTED}:
        return None
    status = packet.get("status")
    if status != "ok":
        return None
    reason = plain_outcome_sentence(packet)
    recommendation_text = "supported" if recommendation == RECOMMEND_SUPPORTED else "refuted"
    message = (
        f"**Something changed:** {experiment.title} now has enough evidence to read as "
        f"{recommendation_text}. {reason} I have not concluded it for you; the experiment "
        "still needs your explicit decision."
    ).replace(".  ", ". ")
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
        # The external cron and in-process scheduler may overlap. Serialize the
        # whole read-budget-candidate-write sequence before looking at state, so
        # a double-fire cannot buy two unsolicited turns for the same user/date.
        await self.session.scalar(
            select(func.pg_advisory_xact_lock(_state_change_lock_key(player.id, as_of)))
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

        budget = await self._budget_decision(player, as_of=as_of, candidate=chosen)
        if not budget.allowed:
            if commit:
                await self.session.commit()
            return StateChangeResult(
                message=None,
                analysis=None,
                message_created=False,
                reason="budget_spent",
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
            "budgetSpend": budget.spend_type,
            "preemptedAnalysisId": (
                str(budget.preempted_analysis_id)
                if budget.preempted_analysis_id is not None
                else None
            ),
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
        current_morning = await self._morning_for_date(player, subject_date=as_of)
        previous_morning = await self._previous_morning(player, as_of=as_of)
        candidates: list[StateChangeCandidate] = []

        # Morning-backed transitions are known only when both sides of the
        # comparison exist. The stored packets are exactly what Mark was shown;
        # recomputing here can disagree with the brief, while treating a missing
        # packet as an empty state invents a change after a holiday or failed read.
        # Since Batch 335 Home shows the week mix counted from the live rows, so the
        # mix's today side is read the same way.
        if (
            current_morning is not None
            and isinstance(current_morning.context_packet, dict)
            and previous_morning is not None
            and isinstance(previous_morning.context_packet, dict)
        ):
            current_packet = current_morning.context_packet
            previous_packet = previous_morning.context_packet

            chronic = _chronic_snapshot_from_packet(current_packet)
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
            # Batch 335 (UX333-02): today's side is the week as it stands, not the
            # morning's packet. On 8 Oct 2026 the 10:45 alert announced a Sweet Spot
            # shortfall 38 minutes after Mark had moved the session to fix it.
            live_mix = await WeeklyMixService(self.session).live_packet(player, current_morning)
            current_mix = (
                _weekly_mix_snapshots(live_mix)
                if live_mix is not None
                else _weekly_mix_snapshots_from_packet(current_packet)
            )
            for snapshot in current_mix:
                candidate = transition_candidate(snapshot, previous_mix.get(snapshot.state_key))
                if candidate is not None:
                    candidates.append(candidate)

        candidates.extend(await self._experiment_candidates(player, as_of=as_of))
        return candidates

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
            result = await service.evaluate(player, experiment, as_of=as_of)
            snapshot = _experiment_snapshot(experiment, evaluation_packet(experiment, result))
            candidate = transition_candidate(snapshot, previous_value)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _morning_for_date(
        self,
        player: Profile,
        *,
        subject_date: date,
    ) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == "morning",
                    Analysis.subject_date == subject_date,
                )
                .order_by(desc(Analysis.generated_at_utc))
                .limit(1)
            ),
        )

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
        target = str(experiment_id)
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
                    Analysis.subject_date < before,
                    Analysis.context_packet.op("->>")("experimentId") == target,
                )
                .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
                .limit(1)
            ),
        )

    async def _budget_decision(
        self,
        player: Profile,
        *,
        as_of: date,
        candidate: StateChangeCandidate,
    ) -> BudgetDecision:
        start = as_of - timedelta(days=BUDGET_WINDOW_DAYS - 1)
        rows = list(
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == ANALYSIS_TYPE_STATE_CHANGE,
                        Analysis.subject_date >= start,
                        Analysis.subject_date <= as_of,
                    )
                    .order_by(Analysis.subject_date, Analysis.generated_at_utc)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return BudgetDecision(allowed=True, spend_type="initial")

        # A window may contain the initial spend and one explicit pre-emption.
        # Multiple legacy/concurrent rows are treated as fully spent rather than
        # using ambiguity to send another unsolicited turn.
        if len(rows) > 1:
            return BudgetDecision(allowed=False)

        previous = rows[0]
        packet = previous.context_packet
        if not isinstance(packet, dict) or packet.get("budgetSpend") == "preemption":
            return BudgetDecision(allowed=False)
        previous_kind = packet.get("transitionKind")
        if previous_kind not in _RANK:
            return BudgetDecision(allowed=False)
        if _RANK[candidate.snapshot.kind] >= _RANK[cast(TransitionKind, previous_kind)]:
            return BudgetDecision(allowed=False)
        return BudgetDecision(
            allowed=True,
            spend_type="preemption",
            preempted_analysis_id=previous.id,
        )
