"""Email automation engine: email_automations, shopper_automation_states,
and invitations.automation_id/automation_step (+ uniqueness guard against
double-sending a step). Reuses invitations/email_jobs/tracking as-is —
automation only owns sequencing/state, never delivery.

Revision ID: 0007_email_automation
Revises: 0006_invitation_visited
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_email_automation"
down_revision = "0006_invitation_visited"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_automations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("step1_template_id", sa.Uuid(), sa.ForeignKey("email_templates.id"), nullable=True),
        sa.Column("step2_template_id", sa.Uuid(), sa.ForeignKey("email_templates.id"), nullable=True),
        sa.Column("step3_template_id", sa.Uuid(), sa.ForeignKey("email_templates.id"), nullable=True),
        sa.Column("wait_days", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_automations_status", "email_automations", ["status"])

    op.create_table(
        "shopper_automation_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("automation_id", sa.Uuid(), sa.ForeignKey("email_automations.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("shopper_id", sa.Uuid(), sa.ForeignKey("shoppers.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event", sa.String(60), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("automation_id", "shopper_id", name="uq_automation_shopper"),
    )
    op.create_index("ix_shopper_automation_states_status", "shopper_automation_states", ["status"])

    with op.batch_alter_table("invitations") as batch_op:
        batch_op.add_column(sa.Column("automation_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("automation_step", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_invitations_automation_id", "email_automations", ["automation_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_unique_constraint(
            "uq_invitation_automation_step", ["automation_id", "shopper_id", "automation_step"]
        )
    op.create_index("ix_invitations_automation_id", "invitations", ["automation_id"])


def downgrade() -> None:
    op.drop_index("ix_invitations_automation_id", table_name="invitations")
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.drop_constraint("uq_invitation_automation_step", type_="unique")
        batch_op.drop_constraint("fk_invitations_automation_id", type_="foreignkey")
        batch_op.drop_column("automation_step")
        batch_op.drop_column("automation_id")
    op.drop_table("shopper_automation_states")
    op.drop_table("email_automations")
