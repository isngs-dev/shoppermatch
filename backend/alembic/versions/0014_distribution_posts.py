"""Add distribution_posts table — Region-Targeted Social Media Posting
(conceptual/demo feature, see services/distribution.py). One row per
simulated post of a campaign's creative to a region-matched destination
(Facebook Group, JobSlinger, or TrustedHerd).

Revision ID: 0014_distribution_posts
Revises: 0013_dynamic_step_templates
Create Date: 2026-08-31
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0014_distribution_posts"
down_revision = "0013_dynamic_step_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distribution_posts",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("destination_type", sa.String(60), nullable=False),
        sa.Column("destination_name", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="posted"),
        sa.Column("posted_by", sa.String(255), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_distribution_posts_campaign_id", "distribution_posts", ["campaign_id"])
    op.create_index("ix_distribution_posts_posted_at", "distribution_posts", ["posted_at"])


def downgrade() -> None:
    op.drop_index("ix_distribution_posts_posted_at", table_name="distribution_posts")
    op.drop_index("ix_distribution_posts_campaign_id", table_name="distribution_posts")
    op.drop_table("distribution_posts")
