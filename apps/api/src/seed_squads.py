"""Idempotent squad seed — loads squads_2026.json into squad_players.

Run from apps/api/ with:
    PYTHONPATH=. DATABASE_URL=<url> python -m src.seed_squads

Safe to re-run: upserts on (team_id, full_name) — existing rows are left
unchanged, only missing players are inserted.
"""

import asyncio
import json
import pathlib
import uuid

from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models.squad import SquadPlayer, SquadPosition
from src.models.team import Team

_DATA = pathlib.Path(__file__).parent / "data" / "squads_2026.json"


async def seed_squads() -> None:
    raw = json.loads(_DATA.read_text())

    async with AsyncSessionLocal() as session:
        # Build team_code → id lookup
        result = await session.execute(select(Team.code, Team.id))
        team_map: dict[str, uuid.UUID] = {row.code: row.id for row in result}

        missing_codes = {r["team_code"] for r in raw} - set(team_map)
        if missing_codes:
            print(f"WARNING: unknown team codes (not in teams table): {missing_codes}")

        # Existing players keyed by (team_id, full_name)
        existing_result = await session.execute(select(SquadPlayer.team_id, SquadPlayer.full_name))
        existing: set[tuple[uuid.UUID, str]] = {
            (row.team_id, row.full_name) for row in existing_result
        }

        inserted = 0
        skipped = 0
        for record in raw:
            team_code = record["team_code"]
            team_id = team_map.get(team_code)
            if team_id is None:
                skipped += 1
                continue

            key = (team_id, record["full_name"])
            if key in existing:
                skipped += 1
                continue

            player = SquadPlayer(
                id=uuid.uuid4(),
                team_id=team_id,
                full_name=record["full_name"],
                known_as=record["known_as"],
                position=SquadPosition(record["position"]),
                shirt_number=record.get("shirt_number"),
                is_active=True,
            )
            session.add(player)
            existing.add(key)
            inserted += 1

        await session.commit()
        print(f"Squad seed complete: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(seed_squads())
