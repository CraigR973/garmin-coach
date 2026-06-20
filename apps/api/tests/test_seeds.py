import pytest

from src.auth import verify_pin
from src.models.profile import PlayerRole
from src.seeds import (
    KILMARNOCK_LATITUDE,
    KILMARNOCK_LONGITUDE,
    MARK_DISPLAY_NAME,
    MARK_GARMIN_USER_PROFILE_PK,
    MARK_HIVE_HOME_ID,
    MARK_TIMEZONE,
    build_mark_profile,
)


def test_build_mark_profile_hashes_pin_and_sets_admin_metadata() -> None:
    profile = build_mark_profile("2468")

    assert profile.display_name == MARK_DISPLAY_NAME
    assert profile.pin_hash != "2468"
    assert verify_pin("2468", profile.pin_hash)
    assert profile.role == PlayerRole.admin
    assert profile.timezone == MARK_TIMEZONE
    assert profile.garmin_user_profile_pk == MARK_GARMIN_USER_PROFILE_PK
    assert profile.hive_home_id == MARK_HIVE_HOME_ID
    assert profile.latitude == KILMARNOCK_LATITUDE
    assert profile.longitude == KILMARNOCK_LONGITUDE
    assert profile.is_active is True


@pytest.mark.parametrize("pin", ["", "123", "12345", "12a4"])
def test_build_mark_profile_rejects_invalid_pin(pin: str) -> None:
    with pytest.raises(ValueError, match="MARK_PIN"):
        build_mark_profile(pin)
