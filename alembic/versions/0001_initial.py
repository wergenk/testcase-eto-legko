"""Initial streams, immutable snapshots, drafts and offer rows."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_stream_id", sa.Integer(), nullable=False),
        sa.Column("keitaro_campaign_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("keitaro_stream_id"),
        sa.CheckConstraint("keitaro_stream_id > 0", name="ck_streams_keitaro_id"),
        sa.CheckConstraint("keitaro_campaign_id > 0", name="ck_streams_campaign_id"),
    )
    op.create_index(
        "ix_streams_keitaro_campaign_id", "streams", ["keitaro_campaign_id"]
    )
    op.create_table(
        "stream_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "stream_id", name="uq_stream_snapshots_id_stream"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_snapshots_payload_object"
        ),
    )
    op.create_index(
        "ix_stream_snapshots_stream_created",
        "stream_snapshots",
        ["stream_id", "created_at", "id"],
    )
    op.create_table(
        "stream_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("base_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("base_editor_state", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["base_snapshot_id", "stream_id"],
            ["stream_snapshots.id", "stream_snapshots.stream_id"],
            name="fk_stream_drafts_base_snapshot_stream",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("stream_id"),
        sa.CheckConstraint("revision >= 1", name="ck_stream_drafts_revision"),
        sa.CheckConstraint(
            "jsonb_typeof(base_editor_state) = 'array'",
            name="ck_stream_drafts_base_editor_array",
        ),
    )
    op.create_table(
        "draft_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("keitaro_offer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("share", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["stream_drafts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "draft_id", "keitaro_offer_id", name="uq_draft_offers_offer"
        ),
        sa.CheckConstraint("keitaro_offer_id > 0", name="ck_draft_offers_keitaro_id"),
        sa.CheckConstraint("share BETWEEN 0 AND 100", name="ck_draft_offers_share"),
        sa.CheckConstraint("position >= 0", name="ck_draft_offers_position"),
        sa.CheckConstraint(
            "is_active OR share = 0", name="ck_draft_offers_archive_share"
        ),
    )
    op.execute("""
        CREATE FUNCTION reject_snapshot_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Stream snapshots are immutable';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER stream_snapshots_immutable
        BEFORE UPDATE ON stream_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_snapshot_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER stream_snapshots_immutable ON stream_snapshots")
    op.execute("DROP FUNCTION reject_snapshot_update()")
    op.drop_table("draft_offers")
    op.drop_table("stream_drafts")
    op.drop_index("ix_stream_snapshots_stream_created", table_name="stream_snapshots")
    op.drop_table("stream_snapshots")
    op.drop_index("ix_streams_keitaro_campaign_id", table_name="streams")
    op.drop_table("streams")
