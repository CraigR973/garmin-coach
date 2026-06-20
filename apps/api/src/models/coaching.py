import uuid
from datetime import date, datetime
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


class ManualEntry(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "manual_entries"
    __table_args__ = (
        Index("ix_manual_entries_user_entry_at", "user_id", "entry_at_utc"),
        Index("ix_manual_entries_user_date", "user_id", "entry_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    bp_systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bp_diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subjective_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    feel: Mapped[str | None] = mapped_column(String(80), nullable=True)
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


class Analysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_user_subject", "user_id", "analysis_type", "subject_date"),
        Index("ix_analyses_activity", "activity_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
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
