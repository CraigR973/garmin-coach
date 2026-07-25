"""Packet boundary for confirmed conversational memory (Batch 151)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def learned_context_packet(knowledge_base: Mapping[str, Any]) -> dict[str, Any]:
    """Return accepted memory with an explicit non-classification contract."""
    raw = knowledge_base.get("learned_context", {})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    return {
        "items": items if isinstance(items, list) else [],
        "classificationImpact": "none",
        "rule": (
            "Use confirmed memory only to personalise context. It cannot alter "
            "verdicts, thresholds, data-quality rules, or objective metrics."
        ),
    }
