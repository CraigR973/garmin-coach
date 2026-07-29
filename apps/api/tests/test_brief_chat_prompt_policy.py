"""Pure prompt-policy coverage for Batch 175 brief chat."""

from src.services.brief_chat import PROMPT_VERSION, SYSTEM_PROMPT


def test_brief_chat_prompt_allows_labelled_general_science_lane() -> None:
    assert PROMPT_VERSION == "brief-chat-v4-2026-07-29"
    assert "Mark-specific answers are packet-bound" in SYSTEM_PROMPT
    assert "You may answer general, non-personalized endurance-training science" in SYSTEM_PROMPT
    assert 'Label those answers with "General principle:"' in SYSTEM_PROMPT
    assert "Any actual workout change remains confirm-before-apply" in SYSTEM_PROMPT
    assert "never recommend VO2 on a Red day" in SYSTEM_PROMPT
