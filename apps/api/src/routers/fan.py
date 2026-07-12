"""Bedroom-fan control endpoints (Batch 27.3).

`PUT /auto` toggles the overnight autopilot (`Profile.fan_auto_enabled`).
`POST /command` drives the fan now over the Dreo cloud and takes manual control
(turns Auto off so the loop does not immediately reconcile the fan back). The
fan list + current intent are read via the daily-loop payload (`thermalState.fans`),
not here, so this router only mutates.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.dreo_fan import DreoFanClient, DreoFanError, DreoFanSnapshot, DreoFanState

router = APIRouter(prefix="/api/v1/fan", tags=["fan"])


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class FanAutoBody(BaseModel):
    enabled: bool


class FanCommandBody(BaseModel):
    fanId: str | None = None
    power: bool | None = None
    speed: int | None = Field(default=None, ge=1, le=9)


class FanSnapshotData(BaseModel):
    id: str
    label: str
    model: str | None = None
    autoTarget: bool
    isOn: bool | None = None
    speed: int | None = None
    oscillating: bool | None = None
    presetMode: str | None = None


class FanStatusData(BaseModel):
    autoEnabled: bool
    fan: FanSnapshotData | None = None


class FanMeta(BaseModel):
    generatedAtUtc: str


class FanEnvelope(BaseModel):
    data: FanStatusData
    meta: FanMeta
    errors: list[str] = Field(default_factory=list)


@router.put("/auto", response_model=FanEnvelope)
async def set_fan_auto(
    body: FanAutoBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> FanEnvelope:
    player.fan_auto_enabled = body.enabled
    await db.commit()
    return FanEnvelope(
        data=FanStatusData(autoEnabled=player.fan_auto_enabled),
        meta=FanMeta(generatedAtUtc=_now()),
    )


@router.post("/command", response_model=FanEnvelope)
async def command_fan(
    body: FanCommandBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> FanEnvelope:
    if body.power is None and body.speed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="power or speed is required",
        )

    try:
        snapshot = await asyncio.to_thread(_drive_fan, body.fanId, body.power, body.speed)
    except DreoFanError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the fan could not be reached",
        ) from exc

    # The command landed: take manual control so the overnight loop does not
    # reconcile the fan back on its next run. (Done only on success — a transient
    # cloud failure must not silently disable the autopilot.)
    player.fan_auto_enabled = False
    await db.commit()

    return FanEnvelope(
        data=FanStatusData(
            autoEnabled=player.fan_auto_enabled,
            fan=_serialize_snapshot(snapshot),
        ),
        meta=FanMeta(generatedAtUtc=_now()),
    )


def _drive_fan(fan_id: str | None, power: bool | None, speed: int | None) -> DreoFanSnapshot:
    client = DreoFanClient()
    client.connect(fan_id=fan_id)
    try:
        if power is not None:
            client.power(power)
        if speed is not None:
            client.set_speed(speed)
        return _selected_snapshot(client, client.read_state())
    finally:
        client.close()


def _selected_snapshot(client: DreoFanClient, state: DreoFanState) -> DreoFanSnapshot:
    selected = next(
        (item for item in client.read_all_states() if item.info.fan_id == client.selected_fan_id),
        None,
    )
    if selected is not None:
        return selected
    info = next(iter(client.list_fans()))
    return DreoFanSnapshot(info=info, state=state)


def _serialize_snapshot(snapshot: DreoFanSnapshot) -> FanSnapshotData:
    return FanSnapshotData(
        id=snapshot.info.fan_id,
        label=snapshot.info.label,
        model=snapshot.info.model,
        autoTarget=snapshot.info.auto_target,
        isOn=snapshot.state.is_on,
        speed=snapshot.state.fan_speed,
        oscillating=snapshot.state.oscillating,
        presetMode=snapshot.state.preset_mode,
    )
