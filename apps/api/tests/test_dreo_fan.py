"""Unit tests for the Dreo bedroom-fan control client (Batch 27.1).

The pydreo SDK is never touched: tests inject a fake PyDreo manager so the
control surface, the mode-before-speed rule (DECISIONS #95), device resolution,
the transport-readiness gate, the token/password fallback, and secret hygiene are
all exercised without network or a real fan.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.services.dreo_fan import (
    MANUAL_PRESET_MODE,
    DreoConnectionError,
    DreoCredentials,
    DreoCredentialsError,
    DreoDeviceNotFoundError,
    DreoFanClient,
    DreoFanState,
)


class FakeWebSocket:
    def __init__(self, closed: bool = False) -> None:
        self.closed = closed


class FakeTransport:
    def __init__(self) -> None:
        self._loop: object | None = None
        self._ws: FakeWebSocket | None = None

    def make_ready(self) -> None:
        self._loop = object()
        self._ws = FakeWebSocket(closed=False)

    def make_closed(self) -> None:
        if self._ws is not None:
            self._ws.closed = True


class FakeDevice:
    """A pydreo device whose control-attribute writes are recorded in order."""

    _CONTROL_ATTRS = {"is_on", "fan_speed", "oscillating", "preset_mode"}

    def __init__(self, **overrides: object) -> None:
        object.__setattr__(self, "commands", [])
        defaults: dict[str, object] = {
            "serial_number": "SN-1",
            "preset_modes": ["normal", "auto", "sleep", "natural", "turbo"],
            "temperature": 75,
            "is_on": False,
            "fan_speed": 7,
            "oscillating": False,
            "preset_mode": "turbo",
        }
        defaults.update(overrides)
        for name, value in defaults.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._CONTROL_ATTRS:
            self.commands.append((name, value))
        object.__setattr__(self, name, value)


class FakeManager:
    """Stand-in for pydreo.PyDreo covering only what DreoFanClient calls."""

    def __init__(
        self,
        *,
        devices: list[object] | None = None,
        login_result: bool = True,
        login_exc: Exception | None = None,
        ready: bool = True,
    ) -> None:
        self.devices = devices if devices is not None else []
        self._login_result = login_result
        self._login_exc = login_exc
        self._ready = ready
        self._transport = FakeTransport()
        self.login_called = False
        self.load_called = False
        self.start_called = False
        self.stop_called = False

    def login(self) -> bool:
        self.login_called = True
        if self._login_exc is not None:
            raise self._login_exc
        return self._login_result

    def load_devices(self) -> None:
        self.load_called = True

    def start_transport(self) -> None:
        self.start_called = True
        if self._ready:
            self._transport.make_ready()

    def stop_transport(self) -> None:
        self.stop_called = True
        self._transport.make_closed()


def _client_using(
    monkeypatch: pytest.MonkeyPatch,
    manager: FakeManager,
    *,
    credentials: DreoCredentials | None = None,
    timeout: float = 0.05,
) -> DreoFanClient:
    """A DreoFanClient whose _build_manager returns the given fake manager."""
    creds = credentials or DreoCredentials(username="mark@example.com", password="pw")
    client = DreoFanClient(creds, transport_ready_timeout_s=timeout)
    monkeypatch.setattr(client, "_build_manager", lambda *, use_token: manager)
    return client


def _connected(
    monkeypatch: pytest.MonkeyPatch, device: FakeDevice
) -> tuple[DreoFanClient, FakeManager]:
    manager = FakeManager(devices=[device])
    client = _client_using(monkeypatch, manager)
    client.connect()
    return client, manager


# -- credentials -----------------------------------------------------------


def test_validate_requires_password_or_token() -> None:
    with pytest.raises(DreoCredentialsError):
        DreoCredentials().validate()
    with pytest.raises(DreoCredentialsError):
        DreoCredentials(username="u").validate()
    # Either a token alone or a username+password pair is sufficient.
    DreoCredentials(token="abc").validate()
    DreoCredentials(username="u", password="p").validate()


def test_build_manager_passes_token_and_uppercases_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturePyDreo:
        def __init__(self, username, password, token=None, region=None) -> None:  # type: ignore[no-untyped-def]
            captured.update(username=username, password=password, token=token, region=region)

    monkeypatch.setitem(sys.modules, "pydreo", types.SimpleNamespace(PyDreo=CapturePyDreo))

    client = DreoFanClient(DreoCredentials(username="u", password="p", token="abc:EU", region="eu"))
    client._build_manager(use_token=True)
    assert captured == {"username": "u", "password": "p", "token": "abc:EU", "region": "EU"}

    # use_token=False forces the password path; empty region becomes None.
    client = DreoFanClient(DreoCredentials(username="u", password="p", token="abc:EU"))
    client._build_manager(use_token=False)
    assert captured["token"] is None
    assert captured["region"] is None


# -- connect / transport ---------------------------------------------------


def test_connect_opens_transport_and_resolves_single_fan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice()
    client, manager = _connected(monkeypatch, device)
    assert client.is_connected
    assert manager.login_called and manager.load_called and manager.start_called


def test_connect_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    client, manager = _connected(monkeypatch, FakeDevice())
    client.connect()  # second call is a no-op
    assert manager.start_called


def test_connect_raises_and_stops_transport_when_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeManager(devices=[FakeDevice()], ready=False)
    client = _client_using(monkeypatch, manager, timeout=0.02)
    with pytest.raises(DreoConnectionError):
        client.connect()
    assert manager.start_called and manager.stop_called
    assert not client.is_connected


def test_login_returning_false_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FakeManager(devices=[FakeDevice()], login_result=False)
    client = _client_using(monkeypatch, manager)
    with pytest.raises(DreoConnectionError):
        client.connect()
    assert not manager.start_called  # never reached the transport


def test_login_exception_does_not_leak_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-pw"
    manager = FakeManager(login_exc=RuntimeError(f"bad login with {secret}"))
    client = _client_using(
        monkeypatch,
        manager,
        credentials=DreoCredentials(username="mark@example.com", password=secret),
    )
    with pytest.raises(DreoConnectionError) as exc_info:
        client.connect()
    assert secret not in str(exc_info.value)


# -- token / password fallback --------------------------------------------


def test_stale_token_falls_back_to_password_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = FakeManager(devices=[FakeDevice()], ready=False)  # token attempt: never ready
    fresh = FakeManager(devices=[FakeDevice()], ready=True)  # password attempt: works
    managers = iter([stale, fresh])
    client = DreoFanClient(
        DreoCredentials(username="u", password="p", token="stale:EU"),
        transport_ready_timeout_s=0.02,
    )
    monkeypatch.setattr(client, "_build_manager", lambda *, use_token: next(managers))

    client.connect()

    assert client.is_connected
    assert stale.stop_called  # the stale-token attempt was cleaned up
    assert fresh.start_called


def test_stale_token_without_password_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = FakeManager(devices=[FakeDevice()], ready=False)
    client = DreoFanClient(DreoCredentials(token="stale:EU"), transport_ready_timeout_s=0.02)
    monkeypatch.setattr(client, "_build_manager", lambda *, use_token: stale)
    with pytest.raises(DreoConnectionError):
        client.connect()
    assert not client.is_connected


# -- device resolution -----------------------------------------------------


def test_resolve_device_by_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    wanted = FakeDevice(serial_number="WANT")
    other = FakeDevice(serial_number="OTHER")
    manager = FakeManager(devices=[other, wanted])
    client = _client_using(
        monkeypatch,
        manager,
        credentials=DreoCredentials(username="u", password="p", device_sn="WANT"),
    )
    client.connect()
    client.power(True)
    assert wanted.is_on is True and other.is_on is False


def test_connect_selects_requested_fan_and_lists_all_fans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeDevice(serial_number="FIRST", name="Bedroom fan")
    second = FakeDevice(serial_number="SECOND", name="Office fan")
    manager = FakeManager(devices=[first, second])
    client = _client_using(monkeypatch, manager)

    client.connect(fan_id="SECOND")

    fans = client.list_fans()
    assert [fan.fan_id for fan in fans] == ["FIRST", "SECOND"]
    assert fans[0].label == "Bedroom fan"
    assert fans[1].label == "Office fan"

    snapshots = client.read_all_states()
    assert [snapshot.info.fan_id for snapshot in snapshots] == ["FIRST", "SECOND"]

    client.power(True)
    assert second.is_on is True
    assert first.is_on is False


def test_unknown_serial_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FakeManager(devices=[FakeDevice(serial_number="OTHER")])
    client = _client_using(
        monkeypatch,
        manager,
        credentials=DreoCredentials(username="u", password="p", device_sn="MISSING"),
    )
    with pytest.raises(DreoDeviceNotFoundError):
        client.connect()


def test_no_controllable_fan_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    not_a_fan = types.SimpleNamespace(serial_number="X")  # lacks is_on / fan_speed
    manager = FakeManager(devices=[not_a_fan])
    client = _client_using(monkeypatch, manager)
    with pytest.raises(DreoDeviceNotFoundError):
        client.connect()


# -- control primitives ----------------------------------------------------


def test_set_speed_switches_to_normal_first_under_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice(preset_mode="turbo", fan_speed=7)
    client, _ = _connected(monkeypatch, device)
    client.set_speed(3)
    # Mode-before-speed: 'normal' must be sent before the WINDLEVEL (DECISIONS #95).
    assert device.commands == [("preset_mode", MANUAL_PRESET_MODE), ("fan_speed", 3)]
    assert device.preset_mode == MANUAL_PRESET_MODE
    assert device.fan_speed == 3


def test_set_speed_skips_mode_switch_when_already_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice(preset_mode="normal", fan_speed=1)
    client, _ = _connected(monkeypatch, device)
    client.set_speed(4)
    assert device.commands == [("fan_speed", 4)]


def test_power_oscillation_and_preset_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice()
    client, _ = _connected(monkeypatch, device)
    client.power(True)
    client.set_oscillation(True)
    client.set_preset_mode("sleep")
    assert device.is_on is True
    assert device.oscillating is True
    assert device.preset_mode == "sleep"


def test_read_state_reflects_device(monkeypatch: pytest.MonkeyPatch) -> None:
    device = FakeDevice(
        is_on=True, fan_speed=5, oscillating=True, preset_mode="normal", temperature=79
    )
    client, _ = _connected(monkeypatch, device)
    assert client.read_state() == DreoFanState(
        is_on=True, fan_speed=5, oscillating=True, preset_mode="normal", temperature=79
    )


def test_control_before_connect_raises() -> None:
    client = DreoFanClient(DreoCredentials(username="u", password="p"))
    with pytest.raises(DreoConnectionError):
        client.power(True)


# -- context manager -------------------------------------------------------


def test_context_manager_connects_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FakeManager(devices=[FakeDevice()])
    client = _client_using(monkeypatch, manager)
    with client as fan:
        assert fan.is_connected
    assert manager.stop_called
    assert not client.is_connected
