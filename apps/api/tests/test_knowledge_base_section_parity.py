"""Coach memory: the web's closed section enum lists exactly what the API sends.

``GET /api/v1/coach-memory`` and ``GET /api/v1/admin/coaching-state`` return every
section in ``PUBLIC_KNOWLEDGE_BASE_SECTIONS``, one per section builder, and the web
parses the reply with the closed ``knowledgeBaseSectionSchema`` enum in
``packages/shared/src/schemas.ts``. A section the enum lacks fails the whole parse, so
the page shows only its error card: internal rows did that in July (Decision #237), and
Batch 231's ``standing_habits`` did it from 28 Aug to 26 Oct (Decision #439), because a
new builder widened the API's list and nothing compared it with the web's.

There is no shared runtime between the two languages, so this test reads the enum from
the TypeScript source and fails the moment the two lists differ in either direction.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.services.coaching_state import PUBLIC_KNOWLEDGE_BASE_SECTIONS

SHARED_SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "shared" / "src" / "schemas.ts"
ENUM_START = "export const knowledgeBaseSectionSchema = z.enum(["


def _web_sections() -> list[str]:
    source = SHARED_SCHEMAS.read_text(encoding="utf-8")
    start = source.index(ENUM_START) + len(ENUM_START)
    body = source[start : source.index("]);", start)]
    return re.findall(r"'([^']+)'", re.sub(r"//[^\n]*", "", body))


def test_the_web_accepts_every_section_the_api_sends() -> None:
    missing = set(PUBLIC_KNOWLEDGE_BASE_SECTIONS) - set(_web_sections())
    assert not missing, f"the web rejects {sorted(missing)}, so Coach memory cannot load"


def test_the_web_lists_no_section_the_api_never_sends() -> None:
    extra = set(_web_sections()) - set(PUBLIC_KNOWLEDGE_BASE_SECTIONS)
    assert not extra, f"no section builder writes {sorted(extra)}"


def test_the_enum_lists_each_section_once() -> None:
    sections = _web_sections()
    assert len(sections) == len(set(sections)) == len(PUBLIC_KNOWLEDGE_BASE_SECTIONS)
