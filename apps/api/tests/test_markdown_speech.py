"""Parity tests against apps/web/src/lib/markdownSpeech.test.ts — the two
implementations must produce identical output for the same input, or
pre-generated audio silently misses the cache the frontend later requests
against."""

from __future__ import annotations

from src.services.markdown_speech import markdown_to_speech_text


def test_strips_markdown_markers_into_readable_speech_text() -> None:
    markdown = "\n".join(
        [
            "# Morning",
            "",
            "- **Green light** — keep the ride.",
            "",
            "Read [Sleep](https://coach.test/sleep).",
        ]
    )

    expected = "Morning\n\nGreen light — keep the ride.\n\nRead Sleep."
    assert markdown_to_speech_text(markdown) == expected


def test_turns_tables_into_spoken_rows_without_separator_noise() -> None:
    markdown = "\n".join(
        [
            "| Metric | Last night |",
            "| --- | --- |",
            "| HRV | 51 |",
        ]
    )

    assert markdown_to_speech_text(markdown) == "Metric, Last night\nHRV, 51"


def test_strips_code_fences() -> None:
    markdown = "Before.\n\n```\ncode block\n```\n\nAfter."
    assert markdown_to_speech_text(markdown) == "Before.\n\ncode block\n\nAfter."


def test_strips_numbered_lists_checkboxes_and_blockquotes() -> None:
    markdown = "\n".join(
        [
            "1. First step",
            "- [ ] Todo item",
            "- [x] Done item",
            "> A quoted line",
        ]
    )
    assert markdown_to_speech_text(markdown) == "First step\nTodo item\nDone item\nA quoted line"


def test_collapses_three_or_more_blank_lines_to_two() -> None:
    markdown = "First.\n\n\n\nSecond."
    assert markdown_to_speech_text(markdown) == "First.\n\nSecond."
