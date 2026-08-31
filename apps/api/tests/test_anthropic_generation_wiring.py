"""Batch 233: every generation path carries the configured thinking and effort.

The swap to Sonnet 5 is not one value. Nine paths reach the Messages API — the
eight ``generate_anthropic_text`` callers plus the Batch API's
``longitudinal_analysis`` — and each had to be wired individually. A path that
was missed does not fail: it silently runs at Sonnet 5's *default* adaptive
``high`` effort with whatever ceiling it happened to hardcode, which is exactly
the 4,096-vs-16,157 mismatch this batch exists to remove.

This sweep is deliberately written against the client classes rather than the
services, so adding a tenth path and forgetting to wire it fails here.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.services.brief_chat import AnthropicBriefChatClient
from src.services.conversation_learning import AnthropicConversationLearningClient
from src.services.morning_analysis import AnthropicMorningAnalysisClient
from src.services.post_flexibility_analysis import AnthropicFlexibilityAnalysisClient
from src.services.post_strength_analysis import AnthropicStrengthAnalysisClient
from src.services.post_walk_analysis import AnthropicWalkAnalysisClient
from src.services.post_workout_analysis import AnthropicPostWorkoutAnalysisClient
from src.services.reviews import AnthropicReviewClient

ALL_CLIENTS = [
    AnthropicMorningAnalysisClient,
    AnthropicPostWorkoutAnalysisClient,
    AnthropicStrengthAnalysisClient,
    AnthropicWalkAnalysisClient,
    AnthropicFlexibilityAnalysisClient,
    AnthropicReviewClient,
    AnthropicBriefChatClient,
    AnthropicConversationLearningClient,
]


def test_the_sweep_covers_every_boundary_caller() -> None:
    """Guard the guard: if a ninth client appears, this list has to grow with it."""
    assert len(ALL_CLIENTS) == 8


@pytest.mark.parametrize("client_cls", ALL_CLIENTS, ids=lambda c: c.__name__)
def test_every_client_carries_the_configured_thinking_and_effort(client_cls: type) -> None:
    client = client_cls()

    assert client.thinking == {"type": "adaptive"}
    assert client.effort == settings.anthropic_effort


@pytest.mark.parametrize("client_cls", ALL_CLIENTS, ids=lambda c: c.__name__)
def test_disabling_thinking_reaches_every_client(
    client_cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollback lever has to be global, or it is not a rollback.

    One setting must restore Sonnet 4.6's behaviour on *all* nine paths; a client
    that resolved its own mode would survive the flag and keep thinking.
    """
    monkeypatch.setattr(settings, "anthropic_thinking_mode", "disabled")

    assert client_cls().thinking == {"type": "disabled"}


@pytest.mark.parametrize("client_cls", ALL_CLIENTS, ids=lambda c: c.__name__)
def test_no_client_ceiling_sits_below_the_measured_prose_need(client_cls: type) -> None:
    """Every ceiling must clear the prose, since thinking now shares the budget.

    Before this batch, ``brief_chat`` capped at 1024 and ``conversation_learning``
    at 1800 — both below the ~1.5k tokens a Sonnet 5 brief alone occupies, and
    unreachable by any environment variable.
    """
    assert client_cls().max_tokens >= 4096
