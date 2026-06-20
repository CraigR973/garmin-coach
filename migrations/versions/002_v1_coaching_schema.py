"""v1 coaching schema

Revision ID: 002
Revises: 001
Create Date: 2026-06-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()"))


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()"))


def _user_fk() -> sa.Column:
    return sa.Column(
        "user_id",
        UUID(as_uuid=True),
        sa.ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")

    op.add_column("profiles", sa.Column("garmin_user_profile_pk", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("hive_home_id", sa.String(100), nullable=True))
    op.add_column("profiles", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("profiles", sa.Column("longitude", sa.Float(), nullable=True))

    op.create_table(
        "daily_metrics",
        _uuid_pk(),
        _user_fk(),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=True),
        sa.Column("readiness_level", sa.String(50), nullable=True),
        sa.Column("readiness_sleep_score", sa.Integer(), nullable=True),
        sa.Column("recovery_time_min", sa.Integer(), nullable=True),
        sa.Column("acute_load", sa.Float(), nullable=True),
        sa.Column("training_status", sa.String(80), nullable=True),
        sa.Column("hrv_last_night_avg_ms", sa.Integer(), nullable=True),
        sa.Column("hrv_weekly_avg_ms", sa.Integer(), nullable=True),
        sa.Column("hrv_status", sa.String(50), nullable=True),
        sa.Column("hrv_baseline_low_ms", sa.Integer(), nullable=True),
        sa.Column("hrv_baseline_high_ms", sa.Integer(), nullable=True),
        sa.Column("resting_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("stress_avg", sa.Float(), nullable=True),
        sa.Column("body_battery_charged", sa.Integer(), nullable=True),
        sa.Column("body_battery_drained", sa.Integer(), nullable=True),
        sa.Column("body_battery_end", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "calendar_date", name="uq_daily_metrics_user_date"),
    )
    op.create_index("ix_daily_metrics_user_date", "daily_metrics", ["user_id", "calendar_date"])

    op.create_table(
        "sleep",
        _uuid_pk(),
        _user_fk(),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("sleep_start_utc", sa.DateTime(), nullable=True),
        sa.Column("sleep_end_utc", sa.DateTime(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("age_adjusted_score", sa.Integer(), nullable=True),
        sa.Column("qualifier", sa.String(80), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("deep_sleep_sec", sa.Integer(), nullable=True),
        sa.Column("light_sleep_sec", sa.Integer(), nullable=True),
        sa.Column("rem_sleep_sec", sa.Integer(), nullable=True),
        sa.Column("awake_sleep_sec", sa.Integer(), nullable=True),
        sa.Column("unmeasurable_sleep_sec", sa.Integer(), nullable=True),
        sa.Column("average_spo2_pct", sa.Float(), nullable=True),
        sa.Column("lowest_spo2_pct", sa.Float(), nullable=True),
        sa.Column("average_respiration", sa.Float(), nullable=True),
        sa.Column("resting_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("avg_overnight_hrv_ms", sa.Integer(), nullable=True),
        sa.Column("hrv_status", sa.String(50), nullable=True),
        sa.Column("avg_sleep_stress", sa.Float(), nullable=True),
        sa.Column("restless_moments_count", sa.Integer(), nullable=True),
        sa.Column("body_battery_change", sa.Integer(), nullable=True),
        sa.Column("factors_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "calendar_date", name="uq_sleep_user_date"),
    )
    op.create_index("ix_sleep_user_date", "sleep", ["user_id", "calendar_date"])

    op.create_table(
        "activities",
        _uuid_pk(),
        _user_fk(),
        sa.Column("garmin_activity_id", sa.BigInteger(), nullable=False),
        sa.Column("garmin_activity_uuid", sa.String(80), nullable=True),
        sa.Column("activity_name", sa.String(200), nullable=False),
        sa.Column("activity_type", sa.String(80), nullable=False),
        sa.Column("start_utc", sa.DateTime(), nullable=False),
        sa.Column("end_utc", sa.DateTime(), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("elapsed_duration_sec", sa.Float(), nullable=True),
        sa.Column("moving_duration_sec", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("avg_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("max_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("avg_power_watts", sa.Integer(), nullable=True),
        sa.Column("max_power_watts", sa.Integer(), nullable=True),
        sa.Column("normalized_power_watts", sa.Integer(), nullable=True),
        sa.Column("intensity_factor", sa.Float(), nullable=True),
        sa.Column("training_load", sa.Float(), nullable=True),
        sa.Column("aerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("anaerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("avg_cadence_rpm", sa.Float(), nullable=True),
        sa.Column("max_cadence_rpm", sa.Float(), nullable=True),
        sa.Column("avg_respiration", sa.Float(), nullable=True),
        sa.Column("max_respiration", sa.Float(), nullable=True),
        sa.Column("min_temperature_c", sa.Float(), nullable=True),
        sa.Column("max_temperature_c", sa.Float(), nullable=True),
        sa.Column("exclude_from_recovery", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "garmin_activity_id", name="uq_activities_user_garmin_id"),
    )
    op.create_index("ix_activities_user_start", "activities", ["user_id", "start_utc"])
    op.create_index("ix_activities_type", "activities", ["activity_type"])

    op.create_table(
        "activity_timeseries",
        _uuid_pk(),
        sa.Column(
            "activity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(), nullable=True),
        sa.Column("elapsed_sec", sa.Float(), nullable=True),
        sa.Column("moving_duration_sec", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("power_watts", sa.Float(), nullable=True),
        sa.Column("heart_rate_bpm", sa.Float(), nullable=True),
        sa.Column("cadence_rpm", sa.Float(), nullable=True),
        sa.Column("respiration", sa.Float(), nullable=True),
        sa.Column("performance_condition", sa.Float(), nullable=True),
        sa.Column("available_stamina", sa.Float(), nullable=True),
        sa.Column("potential_stamina", sa.Float(), nullable=True),
        sa.Column("speed_mps", sa.Float(), nullable=True),
        sa.Column("air_temperature_c", sa.Float(), nullable=True),
        sa.Column("raw_metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("activity_id", "sample_index", name="uq_activity_timeseries_sample"),
    )
    op.create_index(
        "ix_activity_timeseries_activity_timestamp",
        "activity_timeseries",
        ["activity_id", "timestamp_utc"],
    )

    op.create_table(
        "temperature_readings",
        _uuid_pk(),
        _user_fk(),
        sa.Column("source", sa.String(50), nullable=False, server_default="hive"),
        sa.Column("product_id", sa.String(100), nullable=True),
        sa.Column("device_id", sa.String(100), nullable=True),
        sa.Column("captured_at_utc", sa.DateTime(), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=False),
        sa.Column("target_temperature_c", sa.Float(), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "product_id",
            "captured_at_utc",
            name="uq_temperature_reading_source_product_time",
        ),
    )
    op.create_index(
        "ix_temperature_readings_user_time",
        "temperature_readings",
        ["user_id", "captured_at_utc"],
    )

    op.create_table(
        "weather_daily",
        _uuid_pk(),
        _user_fk(),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="open_meteo"),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("temp_high_c", sa.Float(), nullable=True),
        sa.Column("temp_low_c", sa.Float(), nullable=True),
        sa.Column("overnight_low_c", sa.Float(), nullable=True),
        sa.Column("wind_max_mph", sa.Float(), nullable=True),
        sa.Column("wind_gust_mph", sa.Float(), nullable=True),
        sa.Column("precipitation_mm", sa.Float(), nullable=True),
        sa.Column("sunrise_utc", sa.DateTime(), nullable=True),
        sa.Column("sunset_utc", sa.DateTime(), nullable=True),
        sa.Column("raw_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "calendar_date", "source", name="uq_weather_daily_user_date_source"),
    )
    op.create_index("ix_weather_daily_user_date", "weather_daily", ["user_id", "calendar_date"])

    op.create_table(
        "manual_entries",
        _uuid_pk(),
        _user_fk(),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_at_utc", sa.DateTime(), nullable=False),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("subjective_score", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("feel", sa.String(80), nullable=True),
        sa.Column("supplements_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("food_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_manual_entries_user_entry_at", "manual_entries", ["user_id", "entry_at_utc"])
    op.create_index("ix_manual_entries_user_date", "manual_entries", ["user_id", "entry_date"])

    op.create_table(
        "plan_blocks",
        _uuid_pk(),
        _user_fk(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sequence_index", sa.Integer(), nullable=True),
        sa.Column("block_type", sa.String(80), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("goals_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_plan", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "name", "version", name="uq_plan_blocks_user_name_version"),
    )
    op.create_index("ix_plan_blocks_user_dates", "plan_blocks", ["user_id", "start_date", "end_date"])

    op.create_table(
        "planned_workouts",
        _uuid_pk(),
        _user_fk(),
        sa.Column(
            "plan_block_id",
            UUID(as_uuid=True),
            sa.ForeignKey("plan_blocks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workout_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("workout_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="planned"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("planned_duration_min", sa.Integer(), nullable=True),
        sa.Column("intensity_target", sa.String(120), nullable=True),
        sa.Column("structured_workout", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(80), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "workout_date", "version", name="uq_planned_workouts_user_date_version"),
    )
    op.create_index("ix_planned_workouts_user_date", "planned_workouts", ["user_id", "workout_date"])
    op.create_index("ix_planned_workouts_active", "planned_workouts", ["user_id", "is_active"])

    op.create_table(
        "analyses",
        _uuid_pk(),
        _user_fk(),
        sa.Column(
            "activity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("activities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("subject_date", sa.Date(), nullable=False),
        sa.Column("generated_at_utc", sa.DateTime(), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("context_packet", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_markdown", sa.Text(), nullable=False),
        sa.Column("raw_response", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
    )
    op.create_index("ix_analyses_user_subject", "analyses", ["user_id", "analysis_type", "subject_date"])
    op.create_index("ix_analyses_activity", "analyses", ["activity_id"])

    op.create_table(
        "experiments",
        _uuid_pk(),
        _user_fk(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("success_criteria_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observations_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_experiments_user_status", "experiments", ["user_id", "status"])
    op.create_index("ix_experiments_user_dates", "experiments", ["user_id", "start_date", "end_date"])

    op.create_table(
        "knowledge_base",
        _uuid_pk(),
        _user_fk(),
        sa.Column("section", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source", sa.String(120), nullable=True),
        sa.Column("content", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_by_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("user_id", "section", "version", name="uq_knowledge_base_section_version"),
    )
    op.create_index(
        "ix_knowledge_base_user_section_active",
        "knowledge_base",
        ["user_id", "section", "is_active"],
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_table("knowledge_base", schema="coach")
    op.drop_table("experiments", schema="coach")
    op.drop_table("analyses", schema="coach")
    op.drop_table("planned_workouts", schema="coach")
    op.drop_table("plan_blocks", schema="coach")
    op.drop_table("manual_entries", schema="coach")
    op.drop_table("weather_daily", schema="coach")
    op.drop_table("temperature_readings", schema="coach")
    op.drop_table("activity_timeseries", schema="coach")
    op.drop_table("activities", schema="coach")
    op.drop_table("sleep", schema="coach")
    op.drop_table("daily_metrics", schema="coach")
    op.drop_column("profiles", "longitude", schema="coach")
    op.drop_column("profiles", "latitude", schema="coach")
    op.drop_column("profiles", "hive_home_id", schema="coach")
    op.drop_column("profiles", "garmin_user_profile_pk", schema="coach")
