"""multi-league: league_id on leaderboard_snapshots + invites, rewrite scoring trigger.

Revision ID: 012
Revises: 011
Create Date: 2026-05-27

Phase M2 of the multi-league rollout. Two additive columns become NOT
NULL (after a Steele backfill) so per-league fan-out works:

* ``leaderboard_snapshots.league_id`` — snapshot rows are now per
  (player, league). The new index
  ``ix_leaderboard_snapshots_league_player_time`` powers the C-2
  ``DISTINCT ON`` pattern keyed per-league; the secondary ``id DESC``
  sort still breaks ``snapshot_at`` ties from within the same
  transaction (see ``test_leaderboard_dedupes_tied_snapshot_timestamps``
  for the regression that demanded this).
* ``invites.league_id`` — invites are now scoped to the league they
  pull the claimant into.

The ``matches_score_results`` trigger function is replaced. Instead of
one snapshot per active profile it inserts one row per active
``league_memberships`` (joined to active profiles), with rank computed
via ``RANK() OVER (PARTITION BY lm.league_id ORDER BY total_points DESC)``
so each league has its own standings.

Downgrade restores the migration-009 trigger shape verbatim (one
snapshot per active profile, no league fan-out) and drops the new
columns / indexes / FKs. Pre-existing snapshot rows lose their league
context on downgrade; the runbook documents that loss.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- leaderboard_snapshots.league_id ------------------------------------
    op.add_column(
        "leaderboard_snapshots",
        sa.Column("league_id", UUID(as_uuid=True), nullable=True),
    )
    # Backfill from the Steele league if it exists. The subquery returns NULL
    # when no Steele league is present (fresh CI DB) — and since there are no
    # snapshot rows to update in that case, the UPDATE is a harmless no-op.
    op.execute(
        """
        UPDATE leaderboard_snapshots
        SET league_id = (SELECT id FROM leagues WHERE slug = 'steele-spreadsheet')
        WHERE league_id IS NULL
        """
    )
    op.alter_column("leaderboard_snapshots", "league_id", nullable=False)
    op.create_foreign_key(
        "fk_leaderboard_snapshots_league_id",
        "leaderboard_snapshots",
        "leagues",
        ["league_id"],
        ["id"],
    )
    op.execute(
        """
        CREATE INDEX ix_leaderboard_snapshots_league_player_time
            ON leaderboard_snapshots
            (league_id, player_id, snapshot_at DESC, id DESC)
        """
    )

    # --- invites.league_id --------------------------------------------------
    op.add_column(
        "invites",
        sa.Column("league_id", UUID(as_uuid=True), nullable=True),
    )
    # Backfill: map existing invites to the Steele Spreadsheet league.
    # If that league doesn't exist yet (fresh prod deployment where the
    # bootstrap script hasn't run), delete the unmappable invites so the
    # NOT NULL constraint can pass — they'll be re-issued after bootstrap.
    op.execute(
        """
        DELETE FROM invites
        WHERE league_id IS NULL
          AND (SELECT id FROM leagues WHERE slug = 'steele-spreadsheet') IS NULL
        """
    )
    op.execute(
        """
        UPDATE invites
        SET league_id = (SELECT id FROM leagues WHERE slug = 'steele-spreadsheet')
        WHERE league_id IS NULL
        """
    )
    op.alter_column("invites", "league_id", nullable=False)
    op.create_foreign_key(
        "fk_invites_league_id",
        "invites",
        "leagues",
        ["league_id"],
        ["id"],
    )

    # --- Replace the scoring trigger function -------------------------------
    # The function is recompiled lazily; the trigger object created in
    # migration 005 (re-created in 009) keeps firing on the same events.
    op.execute("""
        CREATE OR REPLACE FUNCTION matches_score_results()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        DECLARE
            v_winner_id  UUID;
            v_round_pts  INT;
        BEGIN
            -- 1. Score predictions (group + knockout matches) — unchanged from 005.
            UPDATE predictions p
            SET points_breakdown = calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                ),
                points_awarded = (calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                )->>'total')::int
            WHERE p.match_id = NEW.id
              AND p.deleted_at IS NULL;

            -- 2. Knockout winner predictions: only for knockout-stage matches.
            IF NEW.stage <> 'group' THEN
                IF NEW.actual_home_score > NEW.actual_away_score THEN
                    v_winner_id := NEW.home_team_id;
                ELSIF NEW.actual_home_score < NEW.actual_away_score THEN
                    v_winner_id := NEW.away_team_id;
                ELSE
                    v_winner_id := NEW.penalty_winner_id;
                END IF;

                v_round_pts := CASE NEW.stage
                    WHEN 'r32'         THEN 5
                    WHEN 'r16'         THEN 10
                    WHEN 'qf'          THEN 15
                    WHEN 'sf'          THEN 20
                    WHEN 'third_place' THEN 10
                    WHEN 'final'       THEN 25
                    ELSE 0
                END;

                UPDATE knockout_predictions kp
                SET points_awarded = CASE
                        WHEN v_winner_id IS NOT NULL
                             AND kp.predicted_winner_id = v_winner_id
                        THEN v_round_pts
                        ELSE 0
                    END
                WHERE kp.match_id = NEW.id;
            END IF;

            -- 3. Leaderboard snapshots: fan out per (player, active league).
            --    Rank is partitioned by league_id so each league has its own
            --    standings; predictions stay global so total_points is identical
            --    across leagues for any given player.
            INSERT INTO leaderboard_snapshots (
                id, player_id, league_id, total_points, match_points,
                knockout_winner_points, special_points, rank,
                snapshot_at, triggered_by_match_id
            )
            SELECT
                gen_random_uuid(),
                lm.player_id,
                lm.league_id,
                player_totals.total_points,
                player_totals.match_points,
                player_totals.knockout_winner_points,
                player_totals.special_points,
                RANK() OVER (
                    PARTITION BY lm.league_id
                    ORDER BY player_totals.total_points DESC
                ),
                now(),
                NEW.id
            FROM league_memberships lm
            JOIN (
                SELECT
                    pr.id AS player_id,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0) AS match_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0) AS knockout_winner_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS special_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS total_points
                FROM profiles pr
                WHERE pr.deleted_at IS NULL
            ) AS player_totals ON player_totals.player_id = lm.player_id
            WHERE lm.deleted_at IS NULL;

            RETURN NULL;
        END;
        $func$;
    """)


def downgrade() -> None:
    # --- Restore the migration-009 trigger function verbatim -----------------
    # This is the post-009 body: no WHEN clause on the trigger object (009
    # already dropped it), no league fan-out, one snapshot per active player.
    op.execute("""
        CREATE OR REPLACE FUNCTION matches_score_results()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        DECLARE
            v_winner_id  UUID;
            v_round_pts  INT;
        BEGIN
            UPDATE predictions p
            SET points_breakdown = calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                ),
                points_awarded = (calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                )->>'total')::int
            WHERE p.match_id = NEW.id
              AND p.deleted_at IS NULL;

            IF NEW.stage <> 'group' THEN
                IF NEW.actual_home_score > NEW.actual_away_score THEN
                    v_winner_id := NEW.home_team_id;
                ELSIF NEW.actual_home_score < NEW.actual_away_score THEN
                    v_winner_id := NEW.away_team_id;
                ELSE
                    v_winner_id := NEW.penalty_winner_id;
                END IF;

                v_round_pts := CASE NEW.stage
                    WHEN 'r32'         THEN 5
                    WHEN 'r16'         THEN 10
                    WHEN 'qf'          THEN 15
                    WHEN 'sf'          THEN 20
                    WHEN 'third_place' THEN 10
                    WHEN 'final'       THEN 25
                    ELSE 0
                END;

                UPDATE knockout_predictions kp
                SET points_awarded = CASE
                        WHEN v_winner_id IS NOT NULL
                             AND kp.predicted_winner_id = v_winner_id
                        THEN v_round_pts
                        ELSE 0
                    END
                WHERE kp.match_id = NEW.id;
            END IF;

            INSERT INTO leaderboard_snapshots (
                id, player_id, total_points, match_points,
                knockout_winner_points, special_points, rank,
                snapshot_at, triggered_by_match_id
            )
            SELECT
                gen_random_uuid(),
                player_totals.player_id,
                player_totals.total_points,
                player_totals.match_points,
                player_totals.knockout_winner_points,
                player_totals.special_points,
                RANK() OVER (ORDER BY player_totals.total_points DESC),
                now(),
                NEW.id
            FROM (
                SELECT
                    pr.id AS player_id,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0) AS match_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0) AS knockout_winner_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS special_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS total_points
                FROM profiles pr
                WHERE pr.deleted_at IS NULL
            ) AS player_totals;

            RETURN NULL;
        END;
        $func$;
    """)

    # --- Drop invites.league_id --------------------------------------------
    op.drop_constraint("fk_invites_league_id", "invites", type_="foreignkey")
    op.drop_column("invites", "league_id")

    # --- Drop leaderboard_snapshots.league_id ------------------------------
    op.execute("DROP INDEX IF EXISTS ix_leaderboard_snapshots_league_player_time")
    op.drop_constraint(
        "fk_leaderboard_snapshots_league_id",
        "leaderboard_snapshots",
        type_="foreignkey",
    )
    op.drop_column("leaderboard_snapshots", "league_id")
