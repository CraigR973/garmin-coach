"""Tests for SQLAlchemy model definitions — no DB connection required."""

import src.models  # noqa: F401 — side-effect: registers all models on Base.metadata
from src.models import (
    ActionType,
    ActorType,
    AuditLog,
    Base,
    DeliveryStatus,
    Group,
    Invite,
    JoinRequestStatus,
    KnockoutPrediction,
    LeaderboardSnapshot,
    League,
    LeagueJoinRequest,
    LeagueMemberRole,
    LeagueMembership,
    LeaguePrivacy,
    Match,
    MatchStatus,
    NotificationLog,
    NotificationPreferences,
    NotificationType,
    Prediction,
    Profile,
    PushSubscription,
    RefreshToken,
    ResultSource,
    SiteRole,
    SpecialPrediction,
    SpecialPredictionType,
    SurveyCompletion,
    SurveyResponse,
    Team,
)
from src.models.profile import PlayerRole
from src.models.team import TournamentStage


def test_metadata_has_expected_tables() -> None:
    assert set(Base.metadata.tables.keys()) == {
        "groups",
        "profiles",
        "teams",
        "refresh_tokens",
        "invites",
        "matches",
        "predictions",
        "knockout_predictions",
        "special_predictions",
        "leaderboard_snapshots",
        "leaderboard_tiebreak_overrides",
        "push_subscriptions",
        "notification_preferences",
        "notification_log",
        "audit_log",
        "leagues",
        "league_memberships",
        "league_join_requests",
        "squad_players",
        "survey_completions",
        "survey_responses",
    }


def test_survey_completion_columns() -> None:
    cols = {c.name for c in SurveyCompletion.__table__.columns}
    assert cols == {"id", "player_id", "survey_key", "completed_at"}


def test_survey_response_columns() -> None:
    cols = {c.name for c in SurveyResponse.__table__.columns}
    assert cols == {
        "id",
        "survey_key",
        "league_ids",
        "answers",
        "contact_player_id",
        "created_at",
    }


def test_group_columns() -> None:
    cols = {c.name for c in Group.__table__.columns}
    assert cols == {"id", "name", "created_at", "standings_override"}


def test_profile_columns() -> None:
    cols = {c.name for c in Profile.__table__.columns}
    assert {
        "id",
        "display_name",
        "pin_hash",
        "role",
        "timezone",
        "failed_login_count",
        "locked_until",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_team_columns() -> None:
    cols = {c.name for c in Team.__table__.columns}
    assert {
        "id",
        "name",
        "code",
        "flag_emoji",
        "group_id",
        "eliminated_at_stage",
        "is_host",
        "football_data_team_id",
        "created_at",
    }.issubset(cols)


def test_refresh_token_columns() -> None:
    cols = {c.name for c in RefreshToken.__table__.columns}
    assert {
        "id",
        "player_id",
        "token_hash",
        "device_hint",
        "expires_at",
        "revoked_at",
        "created_at",
    }.issubset(cols)


def test_invite_columns() -> None:
    cols = {c.name for c in Invite.__table__.columns}
    assert {
        "id",
        "token",
        "display_name_hint",
        "created_by",
        "claimed_by",
        "claimed_at",
        "expires_at",
        "is_active",
        "created_at",
    }.issubset(cols)


def test_tournament_stage_values() -> None:
    assert {s.value for s in TournamentStage} == {
        "group",
        "r32",
        "r16",
        "qf",
        "sf",
        "third_place",
        "final",
        "winner",
    }


def test_player_role_values() -> None:
    assert {r.value for r in PlayerRole} == {"player", "admin"}


def test_team_fk_references_groups() -> None:
    fk_targets = {fk.target_fullname for fk in Team.__table__.foreign_keys}
    assert "groups.id" in fk_targets


def test_refresh_token_fk_references_profiles() -> None:
    fk_targets = {fk.target_fullname for fk in RefreshToken.__table__.foreign_keys}
    assert "profiles.id" in fk_targets


def test_invite_fks_reference_profiles() -> None:
    fk_targets = {fk.target_fullname for fk in Invite.__table__.foreign_keys}
    # invites also reference leagues after M2 — that FK is covered by
    # test_invite_has_league_id.
    assert "profiles.id" in fk_targets


def test_profiles_no_longer_has_unique_display_name() -> None:
    # M1 dropped the UNIQUE on display_name (per MD-11); per-league overrides
    # plus derived "First L." rendering handle display.
    constraints = {c.name for c in Profile.__table__.constraints}
    assert "uq_profiles_display_name" not in constraints


def test_profile_has_new_identity_columns() -> None:
    cols = {c.name for c in Profile.__table__.columns}
    assert {"email", "first_name", "last_name", "email_verified_at", "site_role"}.issubset(cols)


def test_site_role_values() -> None:
    assert {r.value for r in SiteRole} == {"superadmin", "user"}


def test_league_columns() -> None:
    cols = {c.name for c in League.__table__.columns}
    assert {
        "id",
        "slug",
        "name",
        "description",
        "privacy",
        "max_members",
        "created_by",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_league_unique_slug() -> None:
    constraint_names = {c.name for c in League.__table__.constraints}
    assert "uq_leagues_slug" in constraint_names
    assert "ck_leagues_max_members_range" in constraint_names


def test_league_fks() -> None:
    fk_targets = {fk.target_fullname for fk in League.__table__.foreign_keys}
    assert "profiles.id" in fk_targets


def test_league_privacy_values() -> None:
    assert {p.value for p in LeaguePrivacy} == {"private", "public_request", "public_open"}


def test_league_membership_columns() -> None:
    cols = {c.name for c in LeagueMembership.__table__.columns}
    assert {
        "id",
        "league_id",
        "player_id",
        "role",
        "display_name_override",
        "joined_at",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_league_membership_unique_pair() -> None:
    constraint_names = {c.name for c in LeagueMembership.__table__.constraints}
    assert "uq_league_memberships_league_player" in constraint_names


def test_league_membership_fks() -> None:
    fk_targets = {fk.target_fullname for fk in LeagueMembership.__table__.foreign_keys}
    assert fk_targets == {"leagues.id", "profiles.id"}


def test_league_member_role_values() -> None:
    assert {r.value for r in LeagueMemberRole} == {"admin", "player"}


def test_league_join_request_columns() -> None:
    cols = {c.name for c in LeagueJoinRequest.__table__.columns}
    assert {
        "id",
        "league_id",
        "player_id",
        "status",
        "requested_at",
        "decided_at",
        "decided_by",
        "decision_note",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_league_join_request_fks() -> None:
    fk_targets = {fk.target_fullname for fk in LeagueJoinRequest.__table__.foreign_keys}
    assert fk_targets == {"leagues.id", "profiles.id"}


def test_join_request_status_values() -> None:
    assert {s.value for s in JoinRequestStatus} == {
        "pending",
        "approved",
        "rejected",
        "cancelled",
    }


def test_groups_has_unique_name() -> None:
    constraints = {c.name for c in Group.__table__.constraints}
    assert "uq_groups_name" in constraints


def test_match_columns() -> None:
    cols = {c.name for c in Match.__table__.columns}
    assert {
        "id",
        "stage",
        "group_id",
        "match_number",
        "home_team_id",
        "away_team_id",
        "home_team_placeholder",
        "away_team_placeholder",
        "kickoff_utc",
        "original_kickoff_utc",
        "venue",
        "status",
        "actual_home_score",
        "actual_away_score",
        "extra_time",
        "penalties",
        "penalty_winner_id",
        "result_source",
        "football_data_match_id",
        "last_synced_at",
        "result_entered_at",
        "result_entered_by",
        "locked_at",
        "postponed_reason",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_match_status_values() -> None:
    assert {s.value for s in MatchStatus} == {
        "scheduled",
        "locked",
        "live",
        "completed",
        "postponed",
        "cancelled",
    }


def test_result_source_values() -> None:
    assert {s.value for s in ResultSource} == {"auto", "manual", "override"}


def test_match_unique_constraints() -> None:
    constraint_names = {c.name for c in Match.__table__.constraints}
    assert "uq_matches_match_number" in constraint_names
    assert "uq_matches_football_data_match_id" in constraint_names


def test_match_indexes() -> None:
    index_names = {i.name for i in Match.__table__.indexes}
    assert "ix_matches_kickoff_utc" in index_names
    assert "ix_matches_stage_status" in index_names
    assert "ix_matches_football_data_match_id" in index_names


def test_match_fks() -> None:
    fk_targets = {fk.target_fullname for fk in Match.__table__.foreign_keys}
    assert "groups.id" in fk_targets
    assert "teams.id" in fk_targets
    assert "profiles.id" in fk_targets


# ---------------------------------------------------------------------------
# Phase 1.3 — Prediction models
# ---------------------------------------------------------------------------


def test_prediction_columns() -> None:
    cols = {c.name for c in Prediction.__table__.columns}
    assert {
        "id",
        "player_id",
        "match_id",
        "predicted_home",
        "predicted_away",
        "submitted_at",
        "update_count",
        "points_awarded",
        "points_breakdown",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_prediction_unique_constraint() -> None:
    constraint_names = {c.name for c in Prediction.__table__.constraints}
    assert "uq_predictions_player_match" in constraint_names


def test_prediction_indexes() -> None:
    index_names = {i.name for i in Prediction.__table__.indexes}
    assert "ix_predictions_player_id" in index_names
    assert "ix_predictions_match_id" in index_names


def test_prediction_fks() -> None:
    fk_targets = {fk.target_fullname for fk in Prediction.__table__.foreign_keys}
    assert "profiles.id" in fk_targets
    assert "matches.id" in fk_targets


def test_prediction_update_count_default() -> None:
    col = Prediction.__table__.c["update_count"]
    assert col.server_default is not None


def test_knockout_prediction_columns() -> None:
    cols = {c.name for c in KnockoutPrediction.__table__.columns}
    assert {
        "id",
        "player_id",
        "match_id",
        "predicted_winner_id",
        "submitted_at",
        "update_count",
        "points_awarded",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_knockout_prediction_unique_constraint() -> None:
    constraint_names = {c.name for c in KnockoutPrediction.__table__.constraints}
    assert "uq_knockout_predictions_player_match" in constraint_names


def test_knockout_prediction_fks() -> None:
    fk_targets = {fk.target_fullname for fk in KnockoutPrediction.__table__.foreign_keys}
    assert "profiles.id" in fk_targets
    assert "matches.id" in fk_targets
    assert "teams.id" in fk_targets


def test_special_prediction_columns() -> None:
    cols = {c.name for c in SpecialPrediction.__table__.columns}
    assert {
        "id",
        "player_id",
        "prediction_type",
        "predicted_team_id",
        "predicted_player_name",
        "submitted_at",
        "points_awarded",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_special_prediction_unique_constraint() -> None:
    constraint_names = {c.name for c in SpecialPrediction.__table__.constraints}
    assert "uq_special_predictions_player_type" in constraint_names


def test_special_prediction_type_values() -> None:
    assert {s.value for s in SpecialPredictionType} == {
        "tournament_winner",
        "golden_boot",
        "top_scoring_team",
        "player_of_tournament",
        "young_player_of_tournament",
        "golden_glove",
    }


def test_leaderboard_snapshot_columns() -> None:
    cols = {c.name for c in LeaderboardSnapshot.__table__.columns}
    assert {
        "id",
        "player_id",
        "league_id",
        "total_points",
        "match_points",
        "knockout_winner_points",
        "special_points",
        "exact_count",
        "correct_result_count",
        "correct_goals_count",
        "specials_correct_count",
        "ko_winner_correct_count",
        "rank",
        "snapshot_at",
        "triggered_by_match_id",
        "created_at",
    }.issubset(cols)


def test_leaderboard_snapshot_indexes() -> None:
    index_names = {i.name for i in LeaderboardSnapshot.__table__.indexes}
    assert "ix_leaderboard_snapshots_snapshot_at_player_id" in index_names
    assert "ix_leaderboard_snapshots_player_id" in index_names


def test_leaderboard_snapshot_fks() -> None:
    fk_targets = {fk.target_fullname for fk in LeaderboardSnapshot.__table__.foreign_keys}
    assert "profiles.id" in fk_targets
    assert "matches.id" in fk_targets
    assert "leagues.id" in fk_targets


def test_leaderboard_snapshot_league_id_not_null() -> None:
    col = LeaderboardSnapshot.__table__.columns["league_id"]
    assert col.nullable is False


def test_invite_has_league_id() -> None:
    cols = {c.name for c in Invite.__table__.columns}
    assert "league_id" in cols
    col = Invite.__table__.columns["league_id"]
    assert col.nullable is False
    fk_targets = {fk.target_fullname for fk in Invite.__table__.foreign_keys}
    assert "leagues.id" in fk_targets


def test_push_subscription_columns() -> None:
    cols = {c.name for c in PushSubscription.__table__.columns}
    assert {
        "id",
        "player_id",
        "subscription",
        "device_hint",
        "failed_send_count",
        "is_active",
        "created_at",
        "last_used_at",
    }.issubset(cols)


def test_push_subscription_defaults() -> None:
    assert PushSubscription.__table__.c["failed_send_count"].server_default is not None
    assert PushSubscription.__table__.c["is_active"].server_default is not None


def test_notification_preferences_columns() -> None:
    cols = {c.name for c in NotificationPreferences.__table__.columns}
    assert {
        "player_id",
        "deadline_warning",
        "predict_reminder",
        "pick_confirmation",
        "match_locked",
        "result_detected",
        "leaderboard_shift",
        "round_complete",
        "match_postponed",
        "special_results",
        "global_mute",
        "quiet_hours_start",
        "quiet_hours_end",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_notification_preferences_pk_is_player_id() -> None:
    pk_cols = {c.name for c in NotificationPreferences.__table__.primary_key}
    assert pk_cols == {"player_id"}


def test_notification_preferences_defaults() -> None:
    t = NotificationPreferences.__table__
    assert t.c["deadline_warning"].server_default is not None
    assert t.c["predict_reminder"].server_default is not None
    assert t.c["pick_confirmation"].server_default is not None
    assert t.c["global_mute"].server_default is not None


# ---------------------------------------------------------------------------
# Phase 1.3 — Notification log & audit log
# ---------------------------------------------------------------------------


def test_notification_log_columns() -> None:
    cols = {c.name for c in NotificationLog.__table__.columns}
    assert {
        "id",
        "player_id",
        "notification_type",
        "title",
        "body",
        "match_id",
        "sent_at",
        "delivery_status",
    }.issubset(cols)


def test_notification_type_values() -> None:
    assert {n.value for n in NotificationType} == {
        "deadline_warning",
        "predict_reminder",
        "pick_confirmation",
        "match_locked",
        "result_detected",
        "leaderboard_shift",
        "round_complete",
        "match_postponed",
        "kickoff_changed",
        "invite_accepted",
        "member_joined",
        "auto_sync_failed",
        "special_results",
        "specials_revealed",
    }


def test_delivery_status_values() -> None:
    assert {s.value for s in DeliveryStatus} == {"sent", "failed", "expired", "suppressed"}


def test_notification_log_indexes() -> None:
    index_names = {i.name for i in NotificationLog.__table__.indexes}
    assert "ix_notification_log_player_id" in index_names
    assert "ix_notification_log_sent_at" in index_names


def test_audit_log_columns() -> None:
    cols = {c.name for c in AuditLog.__table__.columns}
    assert {
        "id",
        "actor_id",
        "actor_type",
        "action_type",
        "target_table",
        "target_id",
        "changes",
        "timestamp",
    }.issubset(cols)


def test_actor_type_values() -> None:
    assert {a.value for a in ActorType} == {"admin", "player", "system"}


def test_action_type_values() -> None:
    assert {a.value for a in ActionType} == {
        "result_auto_fetched",
        "result_manual_entered",
        "result_overridden",
        "match_postponed",
        "match_rescheduled",
        "match_cancelled",
        "match_locked",
        "kickoff_changed",
        "predictions_locked",
        "player_removed",
        "player_pin_reset",
        "invite_created",
        "invite_revoked",
        "knockout_advanced",
        "special_awarded",
        "sync_triggered",
        "sync_failed",
        "tiebreaker_overridden",
        "backup_failed",
        "backup_downloaded",
        # M3 — league lifecycle
        "league_created",
        "league_updated",
        "league_privacy_changed",
        "league_deleted",
        # M3 — membership
        "member_joined",
        "member_left",
        "member_removed",
        "member_promoted",
        "member_demoted",
        # M3 — join requests
        "join_request_created",
        "join_request_approved",
        "join_request_rejected",
        # M3 — per-league invites / PIN reset
        "league_invite_created",
        "league_invite_revoked",
        "league_member_pin_reset",
        "league_join_code_rotated",
    }


def test_audit_log_indexes() -> None:
    index_names = {i.name for i in AuditLog.__table__.indexes}
    assert "ix_audit_log_actor_id" in index_names
    assert "ix_audit_log_timestamp" in index_names
    assert "ix_audit_log_action_type" in index_names


def test_audit_log_actor_id_nullable() -> None:
    assert AuditLog.__table__.c["actor_id"].nullable is True
