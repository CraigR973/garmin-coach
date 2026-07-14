import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin


def _feedback_utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DailyMetric(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", name="uq_daily_metrics_user_date"),
        Index("ix_daily_metrics_user_date", "user_id", "calendar_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    readiness_sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acute_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hrv_last_night_avg_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_weekly_avg_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hrv_baseline_low_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_baseline_high_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resting_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_battery_charged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_drained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Sleep(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "sleep"
    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", name="uq_sleep_user_date"),
        Index("ix_sleep_user_date", "user_id", "calendar_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    sleep_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_adjusted_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualifier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_sleep_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_sleep_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_sleep_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_sleep_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unmeasurable_sleep_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_spo2_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    lowest_spo2_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_respiration: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_overnight_hrv_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avg_sleep_stress: Mapped[float | None] = mapped_column(Float, nullable=True)
    restless_moments_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    factors_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Activity(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "garmin_activity_id", name="uq_activities_user_garmin_id"),
        Index("ix_activities_user_start", "user_id", "start_utc"),
        Index("ix_activities_type", "activity_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    garmin_activity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    garmin_activity_uuid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_power_watts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_power_watts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_power_watts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intensity_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    aerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cadence_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_respiration: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_respiration: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    exclude_from_recovery: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    raw_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ActivityTimeSeries(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "activity_timeseries"
    __table_args__ = (
        UniqueConstraint("activity_id", "sample_index", name="uq_activity_timeseries_sample"),
        Index("ix_activity_timeseries_activity_timestamp", "activity_id", "timestamp_utc"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    elapsed_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    heart_rate_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    cadence_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiration: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_condition: Mapped[float | None] = mapped_column(Float, nullable=True)
    available_stamina: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_stamina: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    air_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TemperatureReading(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "temperature_readings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source",
            "product_id",
            "captured_at_utc",
            name="uq_temperature_reading_source_product_time",
        ),
        Index("ix_temperature_readings_user_time", "user_id", "captured_at_utc"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="hive")
    product_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    target_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class FanStateReading(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One tick of the overnight fan-control loop (Batch 31).

    A genuine 15-min time series mirroring :class:`TemperatureReading`: every
    within-window ``scheduler.run_fan_control`` fire records what the autopilot
    did, so the bedroom chart can show the fan's actual on/off/speed history
    against the room temperature and explain gaps (autopilot off vs cloud
    unreachable vs off-because-cold) rather than going blank. The fan **decision**
    logic is untouched — this only persists the outcome.
    """

    __tablename__ = "fan_state_readings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "captured_at_utc",
            name="uq_fan_state_reading_user_time",
        ),
        Index("ix_fan_state_readings_user_time", "user_id", "captured_at_utc"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    # Overnight loop phase that fired: "control" or "winddown" (never "idle").
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    # The autopilot master switch at fire time (Profile.fan_auto_enabled).
    auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The indoor temperature the decision used; null when no fresh reading.
    observed_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Effective fan state after this tick; null when the fan was not read
    # (autopilot off, or the cloud was unreachable).
    fan_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fan_speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "apply" / "hold" / "no_data" / "auto_off" / "unreachable" / "winddown".
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # Short, secret-safe explanation (decision reason or branch reason).
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class WeatherDaily(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "weather_daily"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "calendar_date", "source", name="uq_weather_daily_user_date_source"
        ),
        Index("ix_weather_daily_user_date", "user_id", "calendar_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="open_meteo")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    temp_high_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_low_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    overnight_low_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    overnight_wind_max_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    overnight_wind_gust_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_max_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gust_mph: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    sunrise_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    sunset_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MetricBaseline(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "metric_baselines"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "metric_key",
            "source",
            name="uq_metric_baselines_user_metric_source",
        ),
        Index("ix_metric_baselines_user_metric", "user_id", "metric_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_label: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="sleep_history_xlsx"
    )
    window_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reliability_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_quartile_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_quartile_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    stddev_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ManualEntry(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "manual_entries"
    __table_args__ = (
        Index("ix_manual_entries_user_entry_at", "user_id", "entry_at_utc"),
        Index("ix_manual_entries_user_date", "user_id", "entry_date"),
        Index("ix_manual_entries_planned_workout", "planned_workout_id"),
        Index("ix_manual_entries_activity", "activity_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    planned_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_workouts.id", ondelete="SET NULL"), nullable=True
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    planned_workout_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    bp_systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subjective_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    feel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    adherence_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_workout_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    supplements_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    food_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlanBlock(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "plan_blocks"
    __table_args__ = (
        UniqueConstraint("user_id", "name", "version", name="uq_plan_blocks_user_name_version"),
        Index("ix_plan_blocks_user_dates", "user_id", "start_date", "end_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    goals_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PlannedWorkout(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "planned_workouts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "workout_date", "version", name="uq_planned_workouts_user_date_version"
        ),
        Index("ix_planned_workouts_user_date", "user_id", "workout_date"),
        Index("ix_planned_workouts_active", "user_id", "is_active"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    plan_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_blocks.id", ondelete="SET NULL"), nullable=True
    )
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    workout_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="planned")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    planned_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intensity_target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    structured_workout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)


class WorkoutDeliveryProposal(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "workout_delivery_proposals"
    __table_args__ = (
        Index("ix_workout_delivery_user_status", "user_id", "status"),
        Index("ix_workout_delivery_planned_workout", "planned_workout_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    planned_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_workouts.id", ondelete="SET NULL"), nullable=True
    )
    planned_workout_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="intervals_icu"
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="proposed")
    proposed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    approved_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    approved_by_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    pushed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    intervals_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    structured_workout_ir: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    intervals_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    zwo_xml: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GarminWorkoutDelivery(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    """Outbound delivery of an outdoor structured workout to Garmin Connect.

    Batch 78 (Decision #151): an outdoor ride is uploaded + scheduled directly on
    Garmin via the existing garth session. Kept separate from
    ``WorkoutDeliveryProposal`` (the intervals.icu/Zwift rail) so the Garmin write
    path is fully isolated. Unique on ``(user_id, workout_date)`` — one live Garmin
    delivery per calendar slot, re-synced in place across Batch 77 re-versioning.
    """

    __tablename__ = "garmin_workout_deliveries"
    __table_args__ = (
        UniqueConstraint("user_id", "workout_date", name="uq_garmin_workout_delivery_user_date"),
        Index("ix_garmin_workout_deliveries_user_status", "user_id", "status"),
        Index("ix_garmin_workout_deliveries_planned_workout", "planned_workout_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    planned_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_workouts.id", ondelete="SET NULL"), nullable=True
    )
    planned_workout_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workout_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pushed")
    garmin_workout_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    garmin_schedule_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    garmin_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    structured_workout_ir: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pushed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class Analysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_user_subject", "user_id", "analysis_type", "subject_date"),
        Index("ix_analyses_activity", "activity_id"),
        Index("ix_analyses_planned_workout", "planned_workout_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    # The planned workout this activity completed (Batch 60), set when the
    # post-session read is generated. Drives the completed-workout state on Home
    # (the read attaches to its session row) and the move-lock (a completed
    # workout can't be re-slotted).
    planned_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_workouts.id", ondelete="SET NULL"), nullable=True
    )
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    context_packet: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Feedback(Base, UUIDPrimaryKeyMixin):
    """Mark's rating + optional free-text correction for one AI summary (Batch 64).

    Every AI summary the app generates is one ``analyses`` row, so feedback is
    keyed to ``analysis_id`` (real referential integrity) rather than a generic
    target type. One row per ``(user, analysis)`` — the endpoint upserts. ``kind``
    picks the rating axis for the surface: ``summary`` (accuracy) or ``suggestion``
    (agreement with a suggested edit). ``rating`` is a short per-axis token; the
    optional ``correction_text`` is the payload that feeds the next read forward
    (Decision #137). ``reason_tags`` are one-tap, kind-scoped "what's off" reasons
    revealed alongside the free-text box on a negative tap (Batch 118).
    """

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "analysis_id", name="uq_feedback_user_analysis"),
        Index("ix_feedback_user_analysis", "user_id", "analysis_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[str] = mapped_column(String(40), nullable=False)
    correction_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_feedback_utcnow
    )


class BriefMessage(Base, UUIDPrimaryKeyMixin):
    """One turn of the follow-up chat on a brief (Batch 119).

    Every AI summary is one ``analyses`` row, so a conversation about a brief
    is keyed to ``analysis_id`` — same referential pattern as ``Feedback``.
    ``role`` is ``user`` or ``assistant``; history threads via ``created_utc``.
    ``proposed_planned_workout_id`` is set on an assistant turn only when the
    deterministic keyword check (not the model) flags the question as wanting
    a plan adjustment and today's planned workout is deliverable; it points at
    the *existing* propose endpoint the frontend calls on confirm, never a new
    mutation path (Decision assigned at Batch 119 kickoff).
    """

    __tablename__ = "brief_messages"
    __table_args__ = (Index("ix_brief_messages_analysis_created", "analysis_id", "created_utc"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    proposed_planned_workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_workouts.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_feedback_utcnow
    )


class Experiment(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "experiments"
    __table_args__ = (
        Index("ix_experiments_user_status", "user_id", "status"),
        Index("ix_experiments_user_dates", "user_id", "start_date", "end_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    success_criteria_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    observations_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "knowledge_base"
    __table_args__ = (
        UniqueConstraint("user_id", "section", "version", name="uq_knowledge_base_section_version"),
        Index("ix_knowledge_base_user_section_active", "user_id", "section", "is_active"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
