"""profiles: add avatar_url nullable column.

Also includes SQL that creates the Supabase Storage bucket and RLS policies
for avatars (public read of unguessable paths, owner write). These statements
are Supabase-specific and will be no-ops on a plain Postgres instance (the
storage schema does not exist there), so the downgrade leaves the bucket
objects in place — just remove the column.

Revision ID: 023
Revises: 022
Create Date: 2026-06-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Supabase Storage bucket + RLS policy SQL.
#
# This SQL targets the `storage` schema that Supabase injects into every
# project. On a plain Postgres CI instance the schema does not exist, so
# we wrap each statement with a DO block that silently skips on error.
#
# Bucket design:
#   - name:     "avatars"
#   - public:   true  → Supabase exposes objects via a public URL without
#               authentication, so <profile.avatar_url> can be used directly
#               in <img> tags.  "Public" in Supabase means the GET endpoint
#               is open; write/delete still require a valid JWT + RLS.
#   - fileSizeLimit: 2 MB (enforced by the upload client-side too)
#   - allowedMimeTypes: image/jpeg, image/png, image/webp, image/gif
#
# RLS policies:
#   - SELECT (public read):  anyone — `true`
#   - INSERT / UPDATE:  auth.uid()::text = storage.foldername(name)[1]
#     Paths are stored as "<player_uuid>/<filename>", so the first folder
#     segment is the owner's UUID.  This enforces owner-only write without
#     a separate owner column.
#
# NOTE: these statements run against the live Supabase project via
# `alembic upgrade head` connected to the Supabase Postgres URL.  If your
# local dev instance uses a plain Postgres container, the DO blocks will
# emit NOTICE messages but will not fail.
# ---------------------------------------------------------------------------

_BUCKET_SQL = """
DO $$
BEGIN
  -- Create the avatars bucket if it doesn't already exist.
  -- Supabase storage.buckets is present only in Supabase-provisioned Postgres.
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    VALUES (
      'avatars',
      'avatars',
      true,
      2097152,  -- 2 MB
      ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    )
    ON CONFLICT (id) DO NOTHING;
  END IF;
END $$;
"""

_RLS_POLICY_SELECT = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    -- Public read: any request may GET an avatar object.
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects'
        AND policyname = 'avatars_public_read'
    ) THEN
      EXECUTE $pol$
        CREATE POLICY avatars_public_read ON storage.objects
          FOR SELECT USING (bucket_id = 'avatars')
      $pol$;
    END IF;
  END IF;
END $$;
"""

_RLS_POLICY_INSERT = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    -- Owner write (INSERT): path must start with the caller's UUID folder.
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects'
        AND policyname = 'avatars_owner_insert'
    ) THEN
      EXECUTE $pol$
        CREATE POLICY avatars_owner_insert ON storage.objects
          FOR INSERT WITH CHECK (
            bucket_id = 'avatars'
            AND auth.uid()::text = (storage.foldername(name))[1]
          )
      $pol$;
    END IF;
  END IF;
END $$;
"""

_RLS_POLICY_UPDATE = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    -- Owner write (UPDATE): same ownership check as INSERT.
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects'
        AND policyname = 'avatars_owner_update'
    ) THEN
      EXECUTE $pol$
        CREATE POLICY avatars_owner_update ON storage.objects
          FOR UPDATE USING (
            bucket_id = 'avatars'
            AND auth.uid()::text = (storage.foldername(name))[1]
          )
      $pol$;
    END IF;
  END IF;
END $$;
"""

_RLS_POLICY_DELETE = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    -- Owner write (DELETE): owner may remove their own objects.
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects'
        AND policyname = 'avatars_owner_delete'
    ) THEN
      EXECUTE $pol$
        CREATE POLICY avatars_owner_delete ON storage.objects
          FOR DELETE USING (
            bucket_id = 'avatars'
            AND auth.uid()::text = (storage.foldername(name))[1]
          )
      $pol$;
    END IF;
  END IF;
END $$;
"""


def upgrade() -> None:
    # 1. Column on profiles
    op.add_column(
        "profiles",
        sa.Column("avatar_url", sa.String(2048), nullable=True),
    )

    # 2. Supabase Storage bucket + RLS policies (silently skip on plain Postgres)
    conn = op.get_bind()
    conn.execute(sa.text(_BUCKET_SQL))
    conn.execute(sa.text(_RLS_POLICY_SELECT))
    conn.execute(sa.text(_RLS_POLICY_INSERT))
    conn.execute(sa.text(_RLS_POLICY_UPDATE))
    conn.execute(sa.text(_RLS_POLICY_DELETE))


def downgrade() -> None:
    op.drop_column("profiles", "avatar_url")
    # Note: bucket objects and RLS policies are left in place on downgrade.
    # Remove them manually via the Supabase dashboard or storage API if needed.
