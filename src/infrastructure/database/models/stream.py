from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORM


class StreamORM(BaseORM):
    __tablename__ = "streams"
    __table_args__ = (
        CheckConstraint("keitaro_stream_id > 0", name="ck_streams_keitaro_id"),
        CheckConstraint("keitaro_campaign_id > 0", name="ck_streams_campaign_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_stream_id: Mapped[int] = mapped_column(unique=True)
    keitaro_campaign_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
