"""Harden legacy RLS policies and set safe function search_path (Batch 164).

Revision ID: 025
Revises: 024
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HARDENED_POLICIES: tuple[str, ...] = (
    "profiles_select_own",
    "profiles_update_own",
    "refresh_tokens_select_own",
    "refresh_tokens_insert_own",
    "refresh_tokens_delete_own",
    "push_subscriptions_select_own",
    "push_subscriptions_insert_own",
    "notification_preferences_select_own",
    "notification_preferences_update_own",
)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION coach.set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path = coach, pg_temp
        AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION coach.set_updated_at() FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                DROP POLICY IF EXISTS "profiles_select_own" ON coach.profiles;
                DROP POLICY IF EXISTS "profiles_update_own" ON coach.profiles;
                DROP POLICY IF EXISTS "refresh_tokens_select_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "refresh_tokens_insert_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "refresh_tokens_delete_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "push_subscriptions_select_own" ON coach.push_subscriptions;
                DROP POLICY IF EXISTS "push_subscriptions_insert_own" ON coach.push_subscriptions;
                DROP POLICY IF EXISTS "notification_preferences_select_own" ON coach.notification_preferences;
                DROP POLICY IF EXISTS "notification_preferences_update_own" ON coach.notification_preferences;

                CREATE POLICY "profiles_select_own"
                    ON coach.profiles
                    FOR SELECT
                    TO authenticated
                    USING ((select auth.uid()) = id);
                CREATE POLICY "profiles_update_own"
                    ON coach.profiles
                    FOR UPDATE
                    TO authenticated
                    USING ((select auth.uid()) = id)
                    WITH CHECK ((select auth.uid()) = id);

                CREATE POLICY "refresh_tokens_select_own"
                    ON coach.refresh_tokens
                    FOR SELECT
                    TO authenticated
                    USING ((select auth.uid()) = user_id);
                CREATE POLICY "refresh_tokens_insert_own"
                    ON coach.refresh_tokens
                    FOR INSERT
                    TO authenticated
                    WITH CHECK ((select auth.uid()) = user_id);
                CREATE POLICY "refresh_tokens_delete_own"
                    ON coach.refresh_tokens
                    FOR DELETE
                    TO authenticated
                    USING ((select auth.uid()) = user_id);

                CREATE POLICY "push_subscriptions_select_own"
                    ON coach.push_subscriptions
                    FOR SELECT
                    TO authenticated
                    USING ((select auth.uid()) = user_id);
                CREATE POLICY "push_subscriptions_insert_own"
                    ON coach.push_subscriptions
                    FOR INSERT
                    TO authenticated
                    WITH CHECK ((select auth.uid()) = user_id);

                CREATE POLICY "notification_preferences_select_own"
                    ON coach.notification_preferences
                    FOR SELECT
                    TO authenticated
                    USING ((select auth.uid()) = user_id);
                CREATE POLICY "notification_preferences_update_own"
                    ON coach.notification_preferences
                    FOR UPDATE
                    TO authenticated
                    USING ((select auth.uid()) = user_id)
                    WITH CHECK ((select auth.uid()) = user_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION coach.set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION coach.set_updated_at() TO PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                DROP POLICY IF EXISTS "profiles_select_own" ON coach.profiles;
                DROP POLICY IF EXISTS "profiles_update_own" ON coach.profiles;
                DROP POLICY IF EXISTS "refresh_tokens_select_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "refresh_tokens_insert_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "refresh_tokens_delete_own" ON coach.refresh_tokens;
                DROP POLICY IF EXISTS "push_subscriptions_select_own" ON coach.push_subscriptions;
                DROP POLICY IF EXISTS "push_subscriptions_insert_own" ON coach.push_subscriptions;
                DROP POLICY IF EXISTS "notification_preferences_select_own" ON coach.notification_preferences;
                DROP POLICY IF EXISTS "notification_preferences_update_own" ON coach.notification_preferences;

                CREATE POLICY "profiles_select_own"
                    ON coach.profiles FOR SELECT USING (auth.uid() = id);
                CREATE POLICY "profiles_update_own"
                    ON coach.profiles FOR UPDATE USING (auth.uid() = id);
                CREATE POLICY "refresh_tokens_select_own"
                    ON coach.refresh_tokens FOR SELECT USING (auth.uid() = user_id);
                CREATE POLICY "refresh_tokens_insert_own"
                    ON coach.refresh_tokens FOR INSERT WITH CHECK (auth.uid() = user_id);
                CREATE POLICY "refresh_tokens_delete_own"
                    ON coach.refresh_tokens FOR DELETE USING (auth.uid() = user_id);
                CREATE POLICY "push_subscriptions_select_own"
                    ON coach.push_subscriptions FOR SELECT USING (auth.uid() = user_id);
                CREATE POLICY "push_subscriptions_insert_own"
                    ON coach.push_subscriptions FOR INSERT WITH CHECK (auth.uid() = user_id);
                CREATE POLICY "notification_preferences_select_own"
                    ON coach.notification_preferences FOR SELECT USING (auth.uid() = user_id);
                CREATE POLICY "notification_preferences_update_own"
                    ON coach.notification_preferences FOR UPDATE USING (auth.uid() = user_id);
            END IF;
        END $$;
        """
    )
