from pathlib import Path

from src.services.handover import _render_baselines


def test_handover_words_are_the_draft_sent_to_craig() -> None:
    draft = (
        Path(__file__).resolve().parents[3] / "docs/drafts/2026-11-05-batch-372-wording.md"
    ).read_text()
    lines: list[str] = []
    _render_baselines(
        lines,
        [
            {
                "metricLabel": "Sleep",
                "mean": 70,
                "median": 72,
                "min": 40,
                "max": 90,
                "sampleCount": 20,
            }
        ],
    )
    assert "| Metric | Usual | Middle value | Lowest | Highest | Readings |" in lines
    header = next(line for line in lines if line.startswith("| Metric |"))
    assert header in draft
