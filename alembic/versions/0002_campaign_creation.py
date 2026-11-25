"""Save resumable campaign creation attempts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_creation_attempts",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("command", postgresql.JSONB(), nullable=False),
        sa.Column("defaults", postgresql.JSONB(), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("geo_stream_id", sa.Integer(), nullable=True),
        sa.Column("offers_stream_id", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "stage IN ('pending', 'campaign', 'geo', 'offers', 'active', 'completed')",
            name="ck_campaign_creation_stage",
        ),
    )


def downgrade() -> None:
    op.drop_table("campaign_creation_attempts")
