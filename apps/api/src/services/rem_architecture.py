"""Does Mark's REM have the shape of REM? (Batch 250 / HS240-05.)

That Mark has a chronic REM deficit is the most persistent thing this app says
about his body. It motivated Batch 61's band model, Batch 72's twelve-lever
library, Batch 227's personal baseline, Batch 230's framing rule and Batch 231's
lever engine — and ``age_norms.REM_FRAMING_RULE`` deliberately forbids the model
from softening it. Every one of those was built on a premise nothing had ever
tested: that ``rem_sleep_sec`` from a wrist device measures REM.

This module is the test. It reads the per-night stage series Garmin already
stores in ``sleep.raw_payload['sleepLevels']`` and asks whether the REM in it is
*architecturally* REM — because that is the one question a total cannot answer.
Real REM clusters in the back half of the night and lengthens through it; a
detector firing on noise produces neither pattern.

**The stage encoding is proved, not assumed.** ``activityLevel`` is an unlabelled
float, so before any of this meant anything the seconds per level were summed and
reconciled against the ``deep_sleep_sec`` / ``light_sleep_sec`` / ``rem_sleep_sec``
/ ``awake_sleep_sec`` columns the app already trusts. Across the twelve most
recent nights every stage agreed to within rounding — deltas of 0.0 to 0.6
minutes — which fixes the mapping in :data:`STAGE_BY_ACTIVITY_LEVEL`.

**What the 212 measured nights say** (production, 2026-09-03; the series exists
on 215 of 437 nights, from 2026-02-01 onward, and those nights carry a mean REM
of 10.47% against 9.69% on the nights without it, so the window is representative
of the outcome in question):

* **The architecture is real, and emphatically so.** REM by quarter of the night
  runs **4.4% → 11.1% → 33.6% → 50.9%**; 84.5% of it falls in the back half, and
  **198 of 212 nights are back-loaded**. Noise does not do this. Half of his REM
  is in the final quarter of the night, which confirms the *mechanism* behind the
  ``protect_last_cycle`` lever for the first time.
* **But two features are not what a genuine, normally-architected REM deficit
  looks like.** Median REM latency is **239 minutes** against a physiological
  norm of 70–120, and the first *detected* episode already averages **17.2
  minutes** where physiology expects the night's shortest, 1–10. Episodes fail to
  lengthen through the night on 54% of nights — a coin flip.
* **Those three facts have one parsimonious joint explanation:** a detector that
  fires only on long, unambiguous REM episodes would miss the short early ones,
  and would therefore report a late first episode, an atypically long "first"
  episode, heavy back-loading, no lengthening trend, and a low total.
* **Part of the long latency is real physiology, and it is measured rather than
  assumed.** Latency correlates with the deep-sleep minutes preceding it at
  **r = +0.387 (95% CI +0.266 to +0.496)** — high early slow-wave pressure genuinely
  delays REM, and Mark's deep sleep runs high. But that explains about a sixth of
  the variance, not the gap.

The honest conclusion is therefore neither of the two the review offered. The
deficit is **not** a pure artefact: the stage series has real, correctly ordered
structure. It is **not** established as a physiological REM deficit either. What
is established is that the app has been reporting a total whose early-night
component is probably under-counted, with a confidence it never earned.

Nothing here removes the flag. :data:`REM_ARCHITECTURE_NOTE` is what the app may
now say instead of saying nothing about it.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Proved against the stage columns rather than taken from documentation — see the
# module docstring. An unlabelled float that everyone "knows" the meaning of is
# exactly the kind of assumption this batch exists to stop making.
STAGE_DEEP = 0.0
STAGE_LIGHT = 1.0
STAGE_REM = 2.0
STAGE_AWAKE = 3.0

STAGE_BY_ACTIVITY_LEVEL: Mapping[float, str] = {
    STAGE_DEEP: "deep",
    STAGE_LIGHT: "light",
    STAGE_REM: "rem",
    STAGE_AWAKE: "awake",
}

# Sleep-onset REM latency in healthy adults, for the comparison the app makes
# when it reports his. Carskadon & Dement's standard account puts the first REM
# episode 70-120 minutes after sleep onset, with the first episode the night's
# shortest and successive ones lengthening.
NORMAL_REM_LATENCY_MIN = (70.0, 120.0)

# Batch 250 (HS240-05 fix step 1). The one sentence the app may say about what
# its REM number is, wherever that number is judged against a band. It states a
# measurement limitation, not a reassurance: it must not be read as "your REM is
# fine", which ``REM_FRAMING_RULE`` still forbids concluding.
REM_ARCHITECTURE_NOTE = (
    "This REM figure is a wrist-device estimate, not a laboratory measurement, and "
    "REM is the stage consumer devices agree with laboratory scoring on least. "
    "Measured across Mark's own 212 nights of stage data, the shape is real — half "
    "his REM falls in the final quarter of the night, as REM should — but the first "
    "REM episode is detected a median of 239 minutes in, against a physiological 70 "
    "to 120, which is what under-counting short early-night REM would look like. "
    "Treat the total as probably understated by an unknown amount, and the pattern "
    "as real."
)


@dataclass(frozen=True)
class SleepSegment:
    """One contiguous stage segment from Garmin's ``sleepLevels``."""

    start: datetime
    end: datetime
    stage: str

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(frozen=True)
class RemEpisode:
    """A run of REM, merged across adjacent segments carrying the same stage."""

    start: datetime
    end: datetime

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(frozen=True)
class NightArchitecture:
    """What one night's stage series says about the shape of its REM."""

    episodes: tuple[RemEpisode, ...]
    night_start: datetime
    night_end: datetime
    quarter_rem_min: tuple[float, float, float, float]
    deep_min_before_first_rem: float

    @property
    def span_min(self) -> float:
        return (self.night_end - self.night_start).total_seconds() / 60.0

    @property
    def total_rem_min(self) -> float:
        return sum(self.quarter_rem_min)

    @property
    def latency_min(self) -> float | None:
        """Minutes from the start of the series to the first detected REM."""
        if not self.episodes:
            return None
        return (self.episodes[0].start - self.night_start).total_seconds() / 60.0

    @property
    def back_half_pct(self) -> float | None:
        """Share of the night's REM falling in the second half. None when no REM."""
        total = self.total_rem_min
        if total <= 0:
            return None
        return 100.0 * (self.quarter_rem_min[2] + self.quarter_rem_min[3]) / total

    @property
    def is_back_loaded(self) -> bool:
        back = self.back_half_pct
        return back is not None and back > 50.0

    @property
    def last_episode_is_longest(self) -> bool:
        if len(self.episodes) < 2:
            return False
        durations = [episode.duration_min for episode in self.episodes]
        return durations[-1] == max(durations)

    @property
    def episodes_lengthen(self) -> bool:
        """True when the back half of the night's episodes outlast the front half."""
        if len(self.episodes) < 2:
            return False
        durations = [episode.duration_min for episode in self.episodes]
        midpoint = len(durations) // 2
        return statistics.fmean(durations[midpoint:]) > statistics.fmean(durations[:midpoint])


def parse_sleep_segments(levels: Any) -> tuple[SleepSegment, ...]:
    """Read ``raw_payload['sleepLevels']`` into typed segments.

    Returns empty for anything unusable, which is the common case: the series is
    JSON ``null`` on 222 of 437 stored nights (every night before 2026-02-01), so
    a caller that assumed a list would fail on half the history.
    """
    if not isinstance(levels, list):
        return ()
    segments: list[SleepSegment] = []
    for raw in levels:
        if not isinstance(raw, Mapping):
            continue
        level = _as_float(raw.get("activityLevel"))
        start = _as_datetime(raw.get("startGMT"))
        end = _as_datetime(raw.get("endGMT"))
        if level is None or start is None or end is None or end <= start:
            continue
        stage = STAGE_BY_ACTIVITY_LEVEL.get(level)
        if stage is None:
            continue
        segments.append(SleepSegment(start=start, end=end, stage=stage))
    segments.sort(key=lambda segment: segment.start)
    return tuple(segments)


def rem_episodes(segments: Sequence[SleepSegment]) -> tuple[RemEpisode, ...]:
    """Contiguous REM runs. Adjacent REM segments are one episode, not two.

    Garmin splits a single stretch of REM across segment boundaries, so counting
    segments rather than merging them would inflate the episode count and deflate
    the mean duration — which is exactly the pair of numbers this analysis reads.
    """
    episodes: list[RemEpisode] = []
    current: RemEpisode | None = None
    for segment in segments:
        if segment.stage != "rem":
            if current is not None:
                episodes.append(current)
                current = None
            continue
        if current is not None and current.end == segment.start:
            current = RemEpisode(start=current.start, end=segment.end)
        else:
            if current is not None:
                episodes.append(current)
            current = RemEpisode(start=segment.start, end=segment.end)
    if current is not None:
        episodes.append(current)
    return tuple(episodes)


def night_architecture(segments: Sequence[SleepSegment]) -> NightArchitecture | None:
    """The shape of one night's REM, or ``None`` when the series cannot carry it."""
    if not segments:
        return None
    night_start = segments[0].start
    night_end = max(segment.end for segment in segments)
    span = (night_end - night_start).total_seconds()
    if span <= 0:
        return None

    episodes = rem_episodes(segments)
    quarters = [0.0, 0.0, 0.0, 0.0]
    for episode in episodes:
        opened = (episode.start - night_start).total_seconds()
        closed = (episode.end - night_start).total_seconds()
        for index in range(4):
            low, high = span * index / 4, span * (index + 1) / 4
            quarters[index] += max(0.0, min(closed, high) - max(opened, low)) / 60.0

    first_rem = episodes[0].start if episodes else None
    deep_before = 0.0
    if first_rem is not None:
        deep_before = sum(
            (min(segment.end, first_rem) - segment.start).total_seconds() / 60.0
            for segment in segments
            if segment.stage == "deep" and segment.start < first_rem
        )

    return NightArchitecture(
        episodes=episodes,
        night_start=night_start,
        night_end=night_end,
        quarter_rem_min=(quarters[0], quarters[1], quarters[2], quarters[3]),
        deep_min_before_first_rem=deep_before,
    )


@dataclass(frozen=True)
class ArchitectureSummary:
    """The aggregate read across every night that carried a stage series."""

    nights: int
    nights_with_rem: int
    mean_episodes: float
    mean_episode_min: float
    median_latency_min: float
    mean_first_episode_min: float
    quarter_share_pct: tuple[float, float, float, float]
    back_loaded_nights: int
    lengthening_nights: int

    @property
    def back_half_pct(self) -> float:
        return self.quarter_share_pct[2] + self.quarter_share_pct[3]

    @property
    def latency_is_physiological(self) -> bool:
        low, high = NORMAL_REM_LATENCY_MIN
        return low <= self.median_latency_min <= high

    @property
    def architecture_is_real(self) -> bool:
        """The review's decision rule: real REM clusters in the back half.

        Deliberately *not* conditioned on the episodes lengthening. On Mark's own
        data the clustering is emphatic (198 of 212 nights) while the lengthening
        is a coin flip, and requiring both would have discarded the one signal the
        data states clearly in order to honour a criterion the data cannot answer.
        """
        return self.back_half_pct > 50.0 and self.back_loaded_nights * 2 > self.nights_with_rem


def summarize_architecture(nights: Iterable[NightArchitecture]) -> ArchitectureSummary | None:
    """Aggregate per-night architecture into the finding, or ``None`` if empty."""
    all_nights = list(nights)
    if not all_nights:
        return None
    with_rem = [night for night in all_nights if night.episodes]
    if not with_rem:
        return ArchitectureSummary(
            nights=len(all_nights),
            nights_with_rem=0,
            mean_episodes=0.0,
            mean_episode_min=0.0,
            median_latency_min=0.0,
            mean_first_episode_min=0.0,
            quarter_share_pct=(0.0, 0.0, 0.0, 0.0),
            back_loaded_nights=0,
            lengthening_nights=0,
        )

    shares: list[list[float]] = [[], [], [], []]
    for night in with_rem:
        total = night.total_rem_min
        if total <= 0:
            continue
        for index in range(4):
            shares[index].append(100.0 * night.quarter_rem_min[index] / total)

    latencies = [night.latency_min for night in with_rem if night.latency_min is not None]
    return ArchitectureSummary(
        nights=len(all_nights),
        nights_with_rem=len(with_rem),
        mean_episodes=statistics.fmean([len(night.episodes) for night in all_nights]),
        mean_episode_min=statistics.fmean(
            [statistics.fmean([e.duration_min for e in night.episodes]) for night in with_rem]
        ),
        median_latency_min=statistics.median(latencies) if latencies else 0.0,
        mean_first_episode_min=statistics.fmean(
            [night.episodes[0].duration_min for night in with_rem]
        ),
        quarter_share_pct=tuple(  # type: ignore[arg-type]
            statistics.fmean(share) if share else 0.0 for share in shares
        ),
        back_loaded_nights=sum(1 for night in with_rem if night.is_back_loaded),
        lengthening_nights=sum(1 for night in with_rem if night.episodes_lengthen),
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None
