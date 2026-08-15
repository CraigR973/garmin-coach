"""Stored prompt metadata helpers.

Generated reads already store the executable prompt version on ``Analysis``.
Context packets keep a compact forensic fingerprint only, not the full system
prompt text, so later chat does not re-ingest instructions as user data.
"""

from __future__ import annotations

import hashlib


def prompt_system_hash(system_prompt: str) -> str:
    """Stable SHA-256 fingerprint for a system prompt."""

    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
