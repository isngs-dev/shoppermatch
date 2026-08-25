"""Add batch_automations — wave-based drip outreach automation.

Revision ID: 0011_batch_automations
Revises: 0010_shop_over_selection
Create Date: 2026-08-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_batch_automations"
down_revision = "0010_shop_over_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_automations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("email_templates.id"), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("wait_days", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("total_iterations", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("current_iteration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_shopper_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sent_shopper_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_batch_automations_status", "batch_automations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_batch_automations_status", table_name="batch_automations")
    op.drop_table("batch_automations")
