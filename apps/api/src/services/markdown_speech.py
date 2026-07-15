"""Markdown-to-spoken-text conversion for the hosted read-aloud voice.

Deliberate line-for-line port of `apps/web/src/lib/markdownSpeech.ts` — this
module exists so `services/tts_pregenerate.py` can compute the exact same
spoken text server-side (for cache-warming) that `BriefListenControls.tsx`
computes client-side before calling `POST /api/v1/tts/synthesize`. Keep the
two in sync; a Python/TS mismatch here means pre-generated audio silently
misses the cache instead of erroring, so drift is easy to miss.
"""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_TABLE_SEPARATOR = re.compile(r"^[:\-|\s]+$")
_HEADING_PREFIX = re.compile(r"^#{1,6}\s+")
_BULLET_PREFIX = re.compile(r"^[-*+]\s+")
_NUMBERED_PREFIX = re.compile(r"^\d+\.\s+")
_CHECKBOX_PREFIX = re.compile(r"^\[[ xX]\]\s+")
_IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"(\*\*|__)(.*?)\1")
_ITALIC = re.compile(r"(\*|_)(.*?)\1")
_STRIKETHROUGH = re.compile(r"~~(.*?)~~")
_BLOCKQUOTE_PREFIX = re.compile(r"^\s*>\s?")
_BLANK_RUN = re.compile(r"\n{3,}")


def _clean_inline_markdown(text: str) -> str:
    text = _IMAGE_LINK.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC.sub(r"\2", text)
    text = _STRIKETHROUGH.sub(r"\1", text)
    text = _BLOCKQUOTE_PREFIX.sub("", text)
    return text.strip()


def _is_markdown_table_separator(line: str) -> bool:
    return bool(_TABLE_SEPARATOR.fullmatch(line)) and "-" in line


def markdown_to_speech_text(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n")
    normalized = _CODE_FENCE.sub(lambda m: m.group(0).replace("```", "").strip(), normalized)
    lines = normalized.split("\n")

    spoken_lines: list[str] = []

    for raw_line in lines:
        trimmed = raw_line.strip()

        if not trimmed:
            if not spoken_lines or spoken_lines[-1] != "":
                spoken_lines.append("")
            continue

        if _is_markdown_table_separator(trimmed):
            continue

        without_prefix = trimmed
        without_prefix = _HEADING_PREFIX.sub("", without_prefix, count=1)
        without_prefix = _BULLET_PREFIX.sub("", without_prefix, count=1)
        without_prefix = _NUMBERED_PREFIX.sub("", without_prefix, count=1)
        without_prefix = _CHECKBOX_PREFIX.sub("", without_prefix, count=1)

        if "|" in without_prefix:
            cells = [_clean_inline_markdown(cell) for cell in without_prefix.split("|")]
            cells = [cell for cell in cells if cell]
            if cells:
                spoken_lines.append(", ".join(cells))
            continue

        cleaned = _clean_inline_markdown(without_prefix)
        if cleaned:
            spoken_lines.append(cleaned)

    joined = "\n".join(spoken_lines)
    return _BLANK_RUN.sub("\n\n", joined).strip()
