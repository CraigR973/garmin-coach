"""Shared currentness rules for regenerable AI artifacts (Batch 159)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from src.models.coaching import Analysis, ManualEntry

INPUT_VERSION_KEY = "inputVersion"


def manual_entry_input_version(entry: ManualEntry | None) -> str | None:
    """Return the stable version represented in an analysis packet for a check-in."""

    if entry is None:
        return None
    value = entry.entry_at_utc
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


def analysis_matches_prompt_and_input(
    analysis: Analysis,
    *,
    prompt_version: str,
    packet_input_key: str,
    input_version: str | None,
) -> bool:
    """Require both the live prompt and the input version stored in its packet."""

    if analysis.prompt_version != prompt_version:
        return False
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    packet_input = packet.get(packet_input_key)
    if input_version is None:
        return packet_input is None
    if not isinstance(packet_input, dict):
        return False
    return packet_input.get("entryAtUtc") == input_version


def packet_input_fingerprint(packet: dict[str, Any]) -> str:
    """Hash deterministic handover inputs while excluding render-time timestamps."""

    stable = {
        key: value
        for key, value in packet.items()
        if key not in {"generatedAtUtc", INPUT_VERSION_KEY}
    }
    encoded = json.dumps(stable, ensure_ascii=True, sort_keys=True, default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stamp_packet_input_version(packet: dict[str, Any]) -> str:
    version = packet_input_fingerprint(packet)
    packet[INPUT_VERSION_KEY] = version
    return version


def analysis_matches_packet_input(
    analysis: Analysis,
    *,
    prompt_version: str,
    input_version: str,
) -> bool:
    if analysis.prompt_version != prompt_version:
        return False
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    return packet.get(INPUT_VERSION_KEY) == input_version


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
