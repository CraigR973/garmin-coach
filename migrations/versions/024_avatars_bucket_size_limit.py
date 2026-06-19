"""avatars bucket: raise file_size_limit 2 MB -> 5 MB.

Lets players upload higher-resolution avatars. The client resizes before
upload, but the larger cap gives headroom and matches the backend's
``MAX_AVATAR_BYTES``. Supabase-specific (targets the ``storage`` schema), so
it's a no-op on a plain Postgres CI instance via the schema-exists guard.

Revision ID: 024
Revises: 023
Create Date: 2026-06-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UP_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage') THEN
    UPDATE storage.buckets SET file_size_limit = 5242880 WHERE id = 'avatars';  -- 5 MB
  END IF;
END $$;
"""

_DOWN_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage') THEN
    UPDATE storage.buckets SET file_size_limit = 2097152 WHERE id = 'avatars';  -- 2 MB
  END IF;
END $$;
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(_UP_SQL))


def downgrade() -> None:
    op.get_bind().execute(sa.text(_DOWN_SQL))
