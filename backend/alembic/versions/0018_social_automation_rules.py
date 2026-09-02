"""Social Media Automation Rules — adds shops.created_at (needed so a
"when a new shop is created" rule can tell a genuinely new shop apart from
one that predates the rule) and the new social_automation_rules table.

See models.py::Shop.created_at / SocialAutomationRule and
services/social_automation.py for the polling evaluator.

Revision ID: 0018_social_automation_rules
Revises: 0017_social_automation
Create Date: 2026-09-02
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0018_social_automation_rules"
down_revision = "0017_social_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shops") as batch_op:
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill existing shops to "now" rather than leaving them NULL — they
    # predate every automation rule that will ever query this column, so
    # any concrete timestamp is correct for the "created before this rule
    # existed" comparison the evaluator relies on.
    op.execute(sa.text("UPDATE shops SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))

    op.create_table(
        "social_automation_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("destination_type", sa.String(30), nullable=False),
        sa.Column("target_kind", sa.String(20), nullable=False, server_default="page"),
        sa.Column("target_ref", sa.String(255), nullable=True),
        sa.Column(
            "template_id", sa.Uuid(), sa.ForeignKey("social_post_templates.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("use_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_tone", sa.String(30), nullable=False, server_default="professional"),
        sa.Column("ai_language", sa.String(60), nullable=False, server_default="English"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule_time", sa.String(8), nullable=True),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_social_automation_rules_client_id", "social_automation_rules", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_social_automation_rules_client_id", table_name="social_automation_rules")
    op.drop_table("social_automation_rules")
    with op.batch_alter_table("shops") as batch_op:
        batch_op.drop_column("created_at")
