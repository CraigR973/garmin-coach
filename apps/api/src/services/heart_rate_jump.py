"""A heart-rate jump on the bike, found in the ride's own trace (Batch 370.2, HS361-05).

On 24 Sep, steady at 136 bpm and 250 W, his heart rate read 186 → 197 → 191 → 181 within
about nine seconds with no change in power, and he stopped pedalling. His note blamed the
strap, and the post-ride read called it a sensor artefact and asked him nothing. Most such
spikes are a dry or slipping strap, but abrupt onset at a steady effort is also the pattern
of a re-entrant tachycardia, and lifelong endurance athletes carry about 2.5 times the risk
of atrial fibrillation. The sports-medicine answer is to ask him once, neutrally, whether he
felt anything; the next morning's Home question does that (``notes_reader.with_ride_jump``).

Pure: the ride's samples in, the jump (or none) out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Final

#: A rise of at least this many beats a minute ...
JUMP_BPM: Final = 30
#: ... within this many seconds ...
JUMP_WINDOW_SEC: Final = 5
#: ... while his power rose by less than this (no rise in effort to explain it).
POWER_RISE_WATTS: Final = 20
#: The jump starts from his steady level: the lowest beat in the window is within this many
#: beats of the 30 seconds before it, so a strap that lost contact and came back is not one.
STEADY_WITHIN_BPM: Final = 10
STEADY_SECONDS: Final = 30
#: Or a heart rate this far above the highest he has recorded on a ride.
ABOVE_MAX_BPM: Final = 10
#: The peak is looked for this long after the jump crossed the line.
PEAK_SECONDS: Final = 10
#: The recorded maximum needs this many rides behind it (his first rides were easy).
MIN_RIDES_FOR_MAX: Final = 20
#: A highest ride maximum this far above the next is a spike, not his maximum.
OUTLIER_BPM: Final = 15

#: ``(elapsed seconds, heart rate, power)``, any of them missing.
Sample = tuple[float | None, float | None, float | None]


@dataclass(frozen=True, slots=True)
class HeartRateJump:
    """The first jump found: where it started and peaked, and how fast."""

    from_bpm: int
    to_bpm: int
    seconds: int
    at_minute: int
    #: True when it is his recorded maximum that was passed, not a jump.
    above_max: bool = False


def _steady_level(
    points: Sequence[tuple[float, float, float | None]], start: float
) -> float | None:
    before = [hr for t, hr, _ in points if start - STEADY_SECONDS <= t < start]
    return float(median(before)) if before else None


def recorded_max_bpm(ride_maxima: Sequence[int | None]) -> int | None:
    """The highest heart rate he has recorded on a ride, from the rides' summaries.

    A lone highest more than :data:`OUTLIER_BPM` above the next is set aside, so one spike
    (24 Sep's 197, against 160 on every other ride) never raises the bar for the next;
    ``None`` with fewer than :data:`MIN_RIDES_FOR_MAX` rides.
    """

    maxima = sorted(value for value in ride_maxima if value)
    if len(maxima) < MIN_RIDES_FOR_MAX:
        return None
    return maxima[-2] if maxima[-1] - maxima[-2] > OUTLIER_BPM else maxima[-1]


def find_heart_rate_jump(
    samples: Sequence[Sample], *, recorded_max_bpm: int | None = None
) -> HeartRateJump | None:
    """The first heart-rate jump in one ride's samples, or ``None``.

    Measured on his 58 rides with a trace since March 2026 (sampled every 2 seconds): it
    finds 24 Sep (136 to 197 in 6 seconds at minute 29) and nothing else.
    """

    points = [
        (float(t), float(hr), None if power is None else float(power))
        for t, hr, power in samples
        if t is not None and hr is not None and hr > 0
    ]
    points.sort(key=lambda point: point[0])
    for index, (t, hr, power) in enumerate(points):
        jump = _jump_at(points, index)
        if jump is not None:
            return jump
        if recorded_max_bpm is not None and hr > recorded_max_bpm + ABOVE_MAX_BPM:
            return HeartRateJump(
                from_bpm=round(points[index - 1][1]) if index else round(hr),
                to_bpm=round(hr),
                seconds=round(t - points[index - 1][0]) if index else 0,
                at_minute=int(t // 60),
                above_max=True,
            )
    return None


def _jump_at(
    points: Sequence[tuple[float, float, float | None]], index: int
) -> HeartRateJump | None:
    t, hr, power = points[index]
    window = [
        point for point in points[max(0, index - 20) : index] if t - point[0] <= JUMP_WINDOW_SEC
    ]
    if not window:
        return None
    low_t, low_hr, low_power = min(window, key=lambda point: point[1])
    if hr - low_hr < JUMP_BPM:
        return None
    if power is not None and low_power is not None and power - low_power >= POWER_RISE_WATTS:
        return None
    steady = _steady_level(points, low_t)
    if steady is None or abs(steady - low_hr) > STEADY_WITHIN_BPM:
        return None
    # Where it peaked, in the seconds after it crossed the line (24 Sep: 186, then 197).
    peak_t, peak_hr, _ = max(
        (point for point in points[index : index + 20] if point[0] - t <= PEAK_SECONDS),
        key=lambda point: point[1],
    )
    return HeartRateJump(
        from_bpm=round(low_hr),
        to_bpm=round(peak_hr),
        seconds=max(1, round(peak_t - low_t)),
        at_minute=int(low_t // 60),
    )
