"""Dreo bedroom-fan cloud control client (Batch 27.1).

A thin, secret-safe wrapper around the ``pydreo_community`` library that drives
Mark's Dreo air-circulator over the **direct Dreo cloud** path (DECISIONS #95) —
no Home Assistant hub. It mirrors the ``HiveClient`` boundary in
``environment_sync.py``: credentials come from env settings and are never exposed
to the frontend, and the third-party SDK import is isolated here so the rest of
the app never imports ``pydreo`` directly.

Lifecycle (see DECISIONS #95)::

    PyDreo(user, pass) -> login() -> load_devices() -> start_transport()
        -> drive via device attribute setters -> stop_transport()

``start_transport()`` opens the command WebSocket on a background daemon thread;
control setters raise ``RuntimeError`` until it is up, and the socket connects
asynchronously, so :meth:`connect` waits for it to be ready before returning.

**Mode-before-speed (load-bearing, DECISIONS #95):** the ``fan_speed`` setter
sends only the ``WINDLEVEL`` and does not change the wind-*type*, so while a
preset such as ``turbo`` is active the motor ignores the requested speed (the
cloud echoes the value but the fan does not change). :meth:`set_speed` therefore
switches the fan to the manual ``normal`` preset first.

The transport-readiness check reads ``pydreo`` internals (it exposes no public
readiness flag), so the dependency is capped below the next major version; the
check fails closed if those internals ever move.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.config import settings

# The manual wind-type in which WINDLEVEL (fan_speed) physically drives the motor.
MANUAL_PRESET_MODE = "normal"

# start_transport() connects the WebSocket on a daemon thread; how long to wait for
# it to be ready before giving up on the first command.
TRANSPORT_READY_TIMEOUT_S = 20.0
_TRANSPORT_POLL_INTERVAL_S = 0.25


class DreoFanError(RuntimeError):
    """Base error for Dreo fan control failures (never carries credentials)."""


class DreoCredentialsError(DreoFanError):
    """Raised when Dreo control cannot start because credentials are incomplete."""


class DreoConnectionError(DreoFanError):
    """Raised when login, the device list, or the command transport is unavailable."""


class DreoDeviceNotFoundError(DreoFanError):
    """Raised when no controllable fan matches on the account."""


@dataclass(frozen=True)
class DreoCredentials:
    username: str = ""
    password: str = ""
    # A previously issued access token, optionally as "token:REGION" (e.g. "abc:EU").
    # When present pydreo skips the password login (resume path, like Garmin/Hive);
    # password stays the fallback for a stale token (see DreoFanClient.connect).
    token: str = ""
    # Optional region hint ("EU"/"NA"); login auto-detects regardless, so this only
    # silences pydreo's "Invalid auth region" warning when set.
    region: str = ""
    # Target device serial; when empty the single controllable fan is used.
    device_sn: str = ""

    @classmethod
    def from_settings(cls) -> DreoCredentials:
        return cls(
            username=settings.dreo_username,
            password=settings.dreo_password,
            token=settings.dreo_token,
            region=settings.dreo_region,
            device_sn=settings.dreo_device_sn,
        )

    def validate(self) -> None:
        if self.token:
            return
        if not self.username or not self.password:
            raise DreoCredentialsError(
                "Dreo credentials are not configured; set DREO_USERNAME and "
                "DREO_PASSWORD (or DREO_TOKEN to resume a cached session)."
            )


@dataclass(frozen=True)
class DreoFanState:
    """A snapshot read of the fan's reported state."""

    is_on: bool | None = None
    fan_speed: int | None = None
    oscillating: bool | None = None
    preset_mode: str | None = None
    temperature: Any | None = None


class DreoFanClient:
    """Sync ``pydreo_community`` wrapper for on/off, speed, oscillation and state.

    Open a session with :meth:`connect` (or use it as a context manager), issue
    control commands, then :meth:`close` to shut the WebSocket down::

        with DreoFanClient() as fan:
            fan.power(True)
            fan.set_speed(3)   # switches to 'normal' first (mode-before-speed)
    """

    def __init__(
        self,
        credentials: DreoCredentials | None = None,
        *,
        transport_ready_timeout_s: float = TRANSPORT_READY_TIMEOUT_S,
    ) -> None:
        self.credentials = credentials or DreoCredentials.from_settings()
        self._transport_ready_timeout_s = transport_ready_timeout_s
        self._manager: Any | None = None
        self._device: Any | None = None

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        """Authenticate, resolve the fan, and open the command transport.

        Idempotent: a no-op once connected. When a cached ``token`` is configured
        it is tried first; if it is stale (login "succeeds" but the transport never
        opens) and a username/password are also configured, a fresh password login
        is attempted once before giving up.
        """
        if self._device is not None:
            return
        self.credentials.validate()

        try:
            self._connect_once(use_token=bool(self.credentials.token))
        except DreoConnectionError:
            can_fall_back = (
                bool(self.credentials.token)
                and bool(self.credentials.username)
                and bool(self.credentials.password)
            )
            if not can_fall_back:
                raise
            self._connect_once(use_token=False)

    def close(self) -> None:
        """Shut the command WebSocket down. Safe to call when not connected."""
        manager, self._manager, self._device = self._manager, None, None
        if manager is not None:
            self._safe_stop(manager)

    def __enter__(self) -> DreoFanClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def is_connected(self) -> bool:
        return self._device is not None

    # -- control primitives ------------------------------------------------

    def power(self, on: bool) -> None:
        """Turn the fan on or off."""
        self._require_device().is_on = bool(on)

    def set_preset_mode(self, mode: str) -> None:
        """Set the wind-type preset (e.g. 'normal', 'auto', 'sleep', 'turbo')."""
        self._require_device().preset_mode = mode

    def set_speed(self, speed: int) -> None:
        """Set the manual fan speed.

        Switches to the manual ``normal`` preset first: under any other preset the
        device accepts the speed value but ignores it physically (DECISIONS #95).
        """
        device = self._require_device()
        if getattr(device, "preset_mode", None) != MANUAL_PRESET_MODE:
            device.preset_mode = MANUAL_PRESET_MODE
        device.fan_speed = int(speed)

    def set_oscillation(self, on: bool) -> None:
        """Start or stop oscillation."""
        self._require_device().oscillating = bool(on)

    def read_state(self) -> DreoFanState:
        """Return the fan's currently reported state."""
        device = self._require_device()
        return DreoFanState(
            is_on=getattr(device, "is_on", None),
            fan_speed=getattr(device, "fan_speed", None),
            oscillating=getattr(device, "oscillating", None),
            preset_mode=getattr(device, "preset_mode", None),
            temperature=getattr(device, "temperature", None),
        )

    # -- internals ---------------------------------------------------------

    def _connect_once(self, *, use_token: bool) -> None:
        manager = self._build_manager(use_token=use_token)
        if not self._login(manager):
            raise DreoConnectionError(
                "Dreo login failed; check DREO_USERNAME/DREO_PASSWORD or DREO_TOKEN."
            )
        self._load_devices(manager)
        device = self._resolve_device(manager)

        manager.start_transport()
        if not self._wait_transport_ready(manager, self._transport_ready_timeout_s):
            self._safe_stop(manager)
            raise DreoConnectionError(
                "Dreo command transport did not become ready within "
                f"{self._transport_ready_timeout_s:.0f}s."
            )

        self._manager = manager
        self._device = device

    def _build_manager(self, *, use_token: bool) -> Any:
        pydreo_cls = self._import_pydreo()
        region = (self.credentials.region or "").upper() or None
        token = (self.credentials.token or None) if use_token else None
        return pydreo_cls(
            self.credentials.username,
            self.credentials.password,
            token=token,
            region=region,
        )

    def _login(self, manager: Any) -> bool:
        try:
            return bool(manager.login())
        except DreoFanError:
            raise
        except Exception as exc:  # surface failure without leaking credentials
            raise DreoConnectionError("Dreo login failed.") from exc

    def _load_devices(self, manager: Any) -> None:
        try:
            manager.load_devices()
        except Exception as exc:
            raise DreoConnectionError("Dreo device list could not be loaded.") from exc

    def _resolve_device(self, manager: Any) -> Any:
        devices = list(getattr(manager, "devices", []) or [])
        if self.credentials.device_sn:
            for device in devices:
                if getattr(device, "serial_number", None) == self.credentials.device_sn:
                    return device
            raise DreoDeviceNotFoundError(
                "Configured Dreo device serial was not found on the account."
            )
        fans = [device for device in devices if _is_controllable_fan(device)]
        if not fans:
            raise DreoDeviceNotFoundError("No controllable Dreo fan found on the account.")
        return fans[0]

    def _wait_transport_ready(self, manager: Any, timeout: float) -> bool:
        """Poll until the command WebSocket is actually connected.

        ``start_transport`` returns immediately while a daemon thread completes the
        handshake; ``send_message`` raises until the loop/socket exist. pydreo
        exposes no public readiness flag, so this reads the transport's internals
        defensively and fails closed (returns ``False``) if they are absent.
        """
        transport = getattr(manager, "_transport", None)
        if transport is None:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            loop = getattr(transport, "_loop", None)
            ws = getattr(transport, "_ws", None)
            if loop is not None and ws is not None and not getattr(ws, "closed", False):
                return True
            time.sleep(_TRANSPORT_POLL_INTERVAL_S)
        return False

    def _require_device(self) -> Any:
        if self._device is None:
            raise DreoConnectionError("Dreo client is not connected; call connect() first.")
        return self._device

    @staticmethod
    def _safe_stop(manager: Any) -> None:
        try:
            manager.stop_transport()
        except Exception:  # best-effort teardown; never mask the original outcome
            pass

    @staticmethod
    def _import_pydreo() -> Any:
        try:
            from pydreo import PyDreo  # type: ignore[import-untyped, unused-ignore]
        except ImportError as exc:  # pragma: no cover - exercised only in missing envs
            raise DreoFanError("pydreo_community is not installed.") from exc
        return PyDreo


def _is_controllable_fan(device: Any) -> bool:
    return hasattr(device, "is_on") and hasattr(device, "fan_speed")
