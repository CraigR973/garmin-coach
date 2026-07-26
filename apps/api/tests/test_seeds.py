from src.models.profile import UserRole
from src.seeds import (
    KILMARNOCK_LATITUDE,
    KILMARNOCK_LONGITUDE,
    MARK_DISPLAY_NAME,
    MARK_GARMIN_USER_PROFILE_PK,
    MARK_HIVE_HOME_ID,
    MARK_TIMEZONE,
    build_mark_profile,
)


def test_build_mark_profile_sets_admin_metadata_without_a_pin() -> None:
    profile = build_mark_profile()

    assert profile.display_name == MARK_DISPLAY_NAME
    assert profile.role == UserRole.admin
    assert profile.timezone == MARK_TIMEZONE
    assert profile.garmin_user_profile_pk == MARK_GARMIN_USER_PROFILE_PK
    assert profile.hive_home_id == MARK_HIVE_HOME_ID
    assert profile.latitude == KILMARNOCK_LATITUDE
    assert profile.longitude == KILMARNOCK_LONGITUDE
    assert profile.is_active is True
