from src.models import Base
from src.models.coaching import Activity, ActivityTimeSeries, DailyMetric, Sleep
from src.models.profile import Profile


def test_v1_domain_tables_are_registered() -> None:
    expected = {
        "daily_metrics",
        "sleep",
        "activities",
        "activity_timeseries",
        "temperature_readings",
        "weather_daily",
        "manual_entries",
        "planned_workouts",
        "plan_blocks",
        "analyses",
        "experiments",
        "knowledge_base",
    }

    assert expected.issubset(Base.metadata.tables.keys())


def test_profile_carries_private_user_source_metadata() -> None:
    profile_columns = Profile.__table__.columns.keys()

    assert "garmin_user_profile_pk" in profile_columns
    assert "hive_home_id" in profile_columns
    assert "timezone" in profile_columns
    assert "latitude" in profile_columns
    assert "longitude" in profile_columns


def test_daily_metric_columns_match_garmin_readiness_samples() -> None:
    columns = DailyMetric.__table__.columns.keys()

    assert "calendar_date" in columns
    assert "readiness_score" in columns
    assert "readiness_level" in columns
    assert "recovery_time_min" in columns
    assert "acute_load" in columns
    assert "hrv_weekly_avg_ms" in columns
    assert "raw_payload" in columns


def test_sleep_columns_keep_garmin_and_app_adjusted_scores_separate() -> None:
    columns = Sleep.__table__.columns.keys()

    assert "score" in columns
    assert "age_adjusted_score" in columns
    assert "rem_sleep_sec" in columns
    assert "average_spo2_pct" in columns
    assert "restless_moments_count" in columns


def test_activity_columns_cover_summary_and_time_series_channels() -> None:
    activity_columns = Activity.__table__.columns.keys()
    series_columns = ActivityTimeSeries.__table__.columns.keys()

    assert "garmin_activity_id" in activity_columns
    assert "normalized_power_watts" in activity_columns
    assert "aerobic_training_effect" in activity_columns
    assert "exclude_from_recovery" in activity_columns
    assert "power_watts" in series_columns
    assert "heart_rate_bpm" in series_columns
    assert "cadence_rpm" in series_columns
    assert "respiration" in series_columns
    assert "performance_condition" in series_columns
    assert "available_stamina" in series_columns
    assert "potential_stamina" in series_columns
