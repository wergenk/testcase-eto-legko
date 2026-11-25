from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORM, TimestampMixin


class CampaignCreationAttemptORM(TimestampMixin, BaseORM):
    __tablename__ = "campaign_creation_attempts"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('pending', 'campaign', 'geo', 'offers', 'active', 'completed')",
            name="ck_campaign_creation_stage",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    command: Mapped[dict] = mapped_column(JSONB)
    defaults: Mapped[dict] = mapped_column(JSONB)
    stage: Mapped[str] = mapped_column(String(16), default="pending")
    campaign_id: Mapped[int | None] = mapped_column(Integer)
    geo_stream_id: Mapped[int | None] = mapped_column(Integer)
    offers_stream_id: Mapped[int | None] = mapped_column(Integer)
