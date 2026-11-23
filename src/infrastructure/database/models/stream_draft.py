from __future__ import annotations

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseORM, TimestampMixin


class StreamDraftORM(BaseORM, TimestampMixin):
    __tablename__ = "stream_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["base_snapshot_id", "stream_id"],
            ["stream_snapshots.id", "stream_snapshots.stream_id"],
            name="fk_stream_drafts_base_snapshot_stream",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision >= 1", name="ck_stream_drafts_revision"),
        CheckConstraint(
            "jsonb_typeof(base_editor_state) = 'array'",
            name="ck_stream_drafts_base_editor_array",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="RESTRICT"), unique=True
    )
    base_snapshot_id: Mapped[int]
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    base_editor_state: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    offers: Mapped[list[DraftOfferORM]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="(DraftOfferORM.position, DraftOfferORM.keitaro_offer_id)",
    )


class DraftOfferORM(BaseORM):
    __tablename__ = "draft_offers"
    __table_args__ = (
        UniqueConstraint("draft_id", "keitaro_offer_id", name="uq_draft_offers_offer"),
        CheckConstraint("keitaro_offer_id > 0", name="ck_draft_offers_keitaro_id"),
        CheckConstraint("share BETWEEN 0 AND 100", name="ck_draft_offers_share"),
        CheckConstraint("position >= 0", name="ck_draft_offers_position"),
        CheckConstraint("is_active OR share = 0", name="ck_draft_offers_archive_share"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("stream_drafts.id", ondelete="CASCADE")
    )
    keitaro_offer_id: Mapped[int]
    name: Mapped[str] = mapped_column(Text)
    share: Mapped[int] = mapped_column(default=0, server_default="0")
    is_pinned: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    position: Mapped[int]
