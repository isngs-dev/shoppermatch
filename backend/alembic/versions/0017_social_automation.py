"""Social Media Automation — real Facebook OAuth on client_social_accounts,
scheduling/publishing fields on distribution_posts, plus new
social_publishing_logs and social_post_templates tables.

See models.py::ClientSocialAccount / DistributionPost / SocialPublishingLog /
SocialPostTemplate and services/facebook_oauth.py, services/facebook_graph.py
for what these back. Every existing column/row on client_social_accounts and
distribution_posts is untouched — this only adds nullable/defaulted columns,
so the pre-existing simulated Distribution flow keeps working unchanged.

Revision ID: 0017_social_automation
Revises: 0016_shop_bonuses
Create Date: 2026-09-02
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0017_social_automation"
down_revision = "0016_shop_bonuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("client_social_accounts") as batch_op:
        batch_op.add_column(sa.Column("external_account_id", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("access_token_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("refresh_token_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="connected"))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("distribution_posts") as batch_op:
        batch_op.add_column(sa.Column("source_type", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("source_shop_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_distribution_posts_source_shop_id",
            "shops",
            ["source_shop_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.add_column(sa.Column("target_kind", sa.String(20), nullable=False, server_default="page"))
        batch_op.add_column(sa.Column("target_ref", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"))
        batch_op.add_column(sa.Column("external_post_id", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("requires_manual_posting", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_index("ix_distribution_posts_scheduled_at", "distribution_posts", ["scheduled_at"])

    op.create_table(
        "social_publishing_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "post_id", sa.Uuid(), sa.ForeignKey("distribution_posts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("target_ref", sa.String(255), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_social_publishing_logs_post_id", "social_publishing_logs", ["post_id"])
    op.create_index("ix_social_publishing_logs_attempted_at", "social_publishing_logs", ["attempted_at"])

    op.create_table(
        "social_post_templates",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(30), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_social_post_templates_client_id", "social_post_templates", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_social_post_templates_client_id", table_name="social_post_templates")
    op.drop_table("social_post_templates")

    op.drop_index("ix_social_publishing_logs_attempted_at", table_name="social_publishing_logs")
    op.drop_index("ix_social_publishing_logs_post_id", table_name="social_publishing_logs")
    op.drop_table("social_publishing_logs")

    op.drop_index("ix_distribution_posts_scheduled_at", table_name="distribution_posts")
    with op.batch_alter_table("distribution_posts") as batch_op:
        batch_op.drop_column("requires_manual_posting")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("error_message")
        batch_op.drop_column("external_post_id")
        batch_op.drop_column("timezone")
        batch_op.drop_column("scheduled_at")
        batch_op.drop_column("target_ref")
        batch_op.drop_column("target_kind")
        batch_op.drop_column("source_shop_id")
        batch_op.drop_column("source_type")

    with op.batch_alter_table("client_social_accounts") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("status")
        batch_op.drop_column("token_expires_at")
        batch_op.drop_column("refresh_token_encrypted")
        batch_op.drop_column("access_token_encrypted")
        batch_op.drop_column("external_account_id")
