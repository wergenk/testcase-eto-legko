from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORM


class StreamSnapshotORM(BaseORM):
    __tablename__ = "stream_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "stream_id", name="uq_stream_snapshots_id_stream"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_snapshots_payload_object"
        ),
        Index("ix_stream_snapshots_stream_created", "stream_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT")
    )
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
