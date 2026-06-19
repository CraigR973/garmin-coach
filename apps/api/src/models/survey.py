"""Survey models — in-app feedback surveys (hybrid anonymity).

The two tables are intentionally decoupled:

- ``SurveyCompletion`` records THAT a player finished a survey (player id +
  survey key) so the client can stop prompting. It is never joined to the
  answers.
- ``SurveyResponse`` holds the de-identified answers plus the auto-tagged
  league ids. ``contact_player_id`` is NULL by default; it is set only when the
  player opts in to being contacted, which is the sole link back to a person.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPrimaryKeyMixin

# Survey key for the "one week in" pulse. Persisted on every row so the same
# tables can host future surveys without a schema change.
WEEK1_PULSE_KEY = "week1_pulse"


class SurveyCompletion(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "survey_completions"
    __table_args__ = (
        UniqueConstraint("player_id", "survey_key", name="uq_survey_completions_player_survey"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    survey_key: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )


class SurveyResponse(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "survey_responses"
    __table_args__ = (Index("ix_survey_responses_survey_key", "survey_key"),)

    survey_key: Mapped[str] = mapped_column(String(64), nullable=False)
    league_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contact_player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
