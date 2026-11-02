"""Batch 365.4 (CR356-02): a CI scan for the rollback-then-read class.

CR236-01, CR327-02 and CR356-01 are one defect at three sites: a handler rolls back, which
expires every loaded instance, then reads an attribute of one (``profile.id``) before
reloading it, and the read raises inside the handler. Each fix covered its own site. This
scans every ``except`` block in ``src``: after a ``rollback()``, no ORM-shaped name may have
an attribute read before a reload. On ``main`` before Batch 365 it found exactly one site,
CR356-01 in ``MorningBriefPipeline._isolated``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
ORM_NAMES = frozenset(
    {"profile", "player", "analysis", "workout", "activity", "entry", "row", "proposal", "plan"}
)
RELOADS = frozenset({"restore_after_rollback", "_restore_after_rollback", "refresh", "get"})


def _called(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            func = item.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def rollback_then_read(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        rolled = False
        for statement in handler.body:
            called = _called(statement)
            if rolled:
                if called & RELOADS:
                    break
                for item in ast.walk(statement):
                    if (
                        isinstance(item, ast.Attribute)
                        and isinstance(item.value, ast.Name)
                        and item.value.id in ORM_NAMES
                        and isinstance(item.ctx, ast.Load)
                    ):
                        hits.append((item.lineno, f"{item.value.id}.{item.attr}"))
                        break
            if "rollback" in called:
                rolled = True
    return hits


def test_no_handler_reads_an_expired_instance_after_its_rollback() -> None:
    found = {
        str(path.relative_to(SRC)): hits
        for path in SRC.rglob("*.py")
        if (hits := rollback_then_read(path.read_text(encoding="utf-8")))
    }
    assert found == {}


def test_the_scan_finds_cr356_01_as_it_was() -> None:
    before = """
async def _isolated(self, run, profile):
    try:
        value = await run()
    except Exception:
        await self.session.rollback()
        log.exception("morning step failed", profile_id=str(profile.id))
        await restore_after_rollback(self.session, profile)
"""
    assert rollback_then_read(before) == [(7, "profile.id")]
