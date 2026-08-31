"""Add client_social_accounts table — connected platforms for Region-
Targeted Social Media Posting (conceptual/demo, see services/distribution.py).
One row per client per platform they've "connected" (Facebook, Instagram,
LinkedIn, Twitter/X, JobSlinger, TrustedHerd); no real OAuth handshake.

Revision ID: 0015_client_social_accounts
Revises: 0014_distribution_posts
Create Date: 2026-08-31
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0015_client_social_accounts"
down_revision = "0014_distribution_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_social_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=False),
        sa.Column("connected_by", sa.String(255), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", "platform", name="uq_client_social_account_platform"),
    )
    op.create_index("ix_client_social_accounts_client_id", "client_social_accounts", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_client_social_accounts_client_id", table_name="client_social_accounts")
    op.drop_table("client_social_accounts")
