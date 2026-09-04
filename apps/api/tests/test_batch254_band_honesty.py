"""Batch 254: the sleep model can finally say "unusually high" (HS240-12/13).

Two findings that are the same defect in two places — a classifier that could
only praise. Band classification was one-sided, so every abnormally *high* value
was congratulated; and the average-comparison descriptors inherited a deliberate
sign flip, so the sentence contradicted the number beside it.
"""

from __future__ import annotations

import pytest

from src.services.age_norms import _classify, _classify_band

# ---------------------------------------------------------------------------
# HS240-12 — more is not always better
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hours", "expected_tone"),
    [
        (6.0, "warn"),  # below the band, unchanged
        (7.5, "good"),  # inside it
        (9.5, "good"),  # modestly above — still a good night
        (12.0, "neutral"),  # a 12-hour night in a man who normally sleeps 7
    ],
)
def test_sleep_duration_is_j_shaped_not_monotone(hours: float, expected_tone: str) -> None:
    """Long sleep in middle-aged adults carries increased all-cause mortality and
    cardiovascular risk in large meta-analyses (Cappuccio et al. 2010, *Sleep*),
    and for an athlete a sudden jump against a stable baseline is a classic marker
    of infection onset or functional overreaching. The classifier returned "good"
    for 9.0, 10.5 **and 12.0** hours alike."""
    tone, _ = _classify_band(hours, 7, 9, "higher")
    assert tone == expected_tone


def test_a_rem_rebound_is_no_longer_congratulated() -> None:
    """A REM fraction at 45% is not a good night; it is rebound, and its common
    triggers — recent REM deprivation, alcohol cessation, stopping a
    REM-suppressing medication — are exactly the context in which the app's REM
    narrative should change."""
    tone, descriptor = _classify_band(45, 15, 25, "higher")
    assert tone == "neutral"
    assert "worth noticing" in descriptor


def test_an_implausibly_deep_night_reads_as_unusual_rather_than_excellent() -> None:
    """A deep fraction at 40% is profound sleep debt or a device artefact."""
    tone, descriptor = _classify_band(40, 12, 20, "higher")
    assert tone == "neutral"
    assert "Well above" in descriptor


def test_the_far_tier_is_neutral_rather_than_a_failure() -> None:
    """ "Worth noticing" is what the data supports. Calling an unusually
    good-looking night a failure would be its own dishonesty."""
    for value, low, high in ((12.0, 7, 9), (45, 15, 25), (40, 12, 20)):
        tone, _ = _classify_band(value, low, high, "higher")
        assert tone != "warn"


def test_a_lower_is_better_metric_gets_the_same_treatment() -> None:
    """An awake fraction near zero is a device artefact before it is a triumph."""
    good_tone, _ = _classify_band(3, 5, 15, "lower")
    assert good_tone == "good"
    far_tone, far_descriptor = _classify_band(-6, 5, 15, "lower")
    assert far_tone == "neutral"
    assert "worth noticing" in far_descriptor


def test_the_ordinary_good_night_is_still_a_good_night() -> None:
    """The tier must not fire on values Mark actually sees. His nights sit inside
    or just outside the bands; the far tier is a full band width beyond the edge."""
    assert _classify_band(8.0, 7, 9, "higher")[0] == "good"
    assert _classify_band(10.5, 7, 9, "higher")[0] == "good"
    assert _classify_band(22, 15, 25, "higher")[0] == "good"
    assert _classify_band(28, 15, 25, "higher")[0] == "good"


# ---------------------------------------------------------------------------
# HS240-13 — the sentence must not contradict the number beside it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("resting_hr", "expected_descriptor"),
    [
        (47, "Much better than average"),
        (71, "About average"),
        (74, "Above average"),
        (110, "Well above average"),
    ],
)
def test_a_high_resting_hr_no_longer_reads_as_below_average(
    resting_hr: float, expected_descriptor: str
) -> None:
    """A resting heart rate of **110** was displayed as *"Well below average"* —
    next to the value 110 and an age average of 71. The tone was right and the
    sentence said the opposite of the fact. Batch 230 exists because every figure
    on the morning brief reconciles from what it shows; this one did not, and it
    is rendered on two tables **and shipped to the model**."""
    _, descriptor = _classify(resting_hr, 71, "lower")
    assert descriptor == expected_descriptor


def test_the_tone_mapping_is_unchanged_by_the_rewording() -> None:
    """`gap` is deliberately sign-flipped so a green tone always reads as good.
    That half was never wrong and must not move."""
    assert _classify(47, 71, "lower")[0] == "good"
    assert _classify(110, 71, "lower")[0] == "warn"
    assert _classify(55, 40, "higher")[0] == "good"
    assert _classify(30, 40, "higher")[0] == "warn"


def test_a_higher_is_better_metric_still_says_below() -> None:
    """The direction word follows the metric, not the tone."""
    assert _classify(30, 40, "higher")[1] == "Well below average"
    assert _classify(37, 40, "higher")[1] == "Below average"


def test_an_implausibly_low_resting_hr_is_noticed_rather_than_praised() -> None:
    """The low side was unbounded: an RHR of 30 read "Much better than average"
    with no floor. For a trained 57-year-old the 40s are normal and expected, so
    the floor sits below them — and the app says the value is *unusual*, not what
    it means."""
    tone, descriptor = _classify(30, 71, "lower", plausible_floor=35)
    assert tone == "neutral"
    assert "Unusually low" in descriptor
    # Normal-for-trained stays good.
    assert _classify(42, 71, "lower", plausible_floor=35)[0] == "good"


def test_the_floor_is_opt_in_per_metric() -> None:
    """Only metrics with a defensible implausibility floor carry one."""
    assert _classify(30, 71, "lower")[0] == "good"
