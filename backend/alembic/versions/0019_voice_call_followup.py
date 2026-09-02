"""AI Voice Call Follow-Up (Automated Shopper Outreach & Follow-Up, step 07)
— adds voice-call config to email_automations, per-shopper voice-call state
to shopper_automation_states, and a new voice_call_logs table.

See models.py::EmailAutomation / ShopperAutomationState / VoiceCallLog and
services/voice_call.py (Twilio), services/voice_call_ai.py (the GPT-driven
conversation), services/voice_call_scheduler.py (the poller). Every existing
column/row is untouched — additive only, so the email-only sequence keeps
working unchanged for every automation that doesn't opt in.

Revision ID: 0019_voice_call_followup
Revises: 0018_social_automation_rules
Create Date: 2026-09-03
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0019_voice_call_followup"
down_revision = "0018_social_automation_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.add_column(sa.Column("voice_call_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("voice_call_delay_days", sa.Integer(), nullable=False, server_default="2"))
        batch_op.add_column(sa.Column("voice_call_retry_gap_days", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("voice_call_max_attempts", sa.Integer(), nullable=False, server_default="2"))

    with op.batch_alter_table("shopper_automation_states") as batch_op:
        batch_op.add_column(sa.Column("voice_call_status", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("voice_call_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("voice_call_next_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("voice_call_outcome", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("voice_call_last_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "voice_call_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "automation_state_id",
            sa.Uuid(),
            sa.ForeignKey("shopper_automation_states.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_call_sid", sa.String(64), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_voice_call_logs_automation_state_id", "voice_call_logs", ["automation_state_id"])
    op.create_index("ix_voice_call_logs_external_call_sid", "voice_call_logs", ["external_call_sid"])
    op.create_index("ix_voice_call_logs_attempted_at", "voice_call_logs", ["attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_voice_call_logs_attempted_at", table_name="voice_call_logs")
    op.drop_index("ix_voice_call_logs_external_call_sid", table_name="voice_call_logs")
    op.drop_index("ix_voice_call_logs_automation_state_id", table_name="voice_call_logs")
    op.drop_table("voice_call_logs")

    with op.batch_alter_table("shopper_automation_states") as batch_op:
        batch_op.drop_column("voice_call_last_at")
        batch_op.drop_column("voice_call_outcome")
        batch_op.drop_column("voice_call_next_at")
        batch_op.drop_column("voice_call_attempts")
        batch_op.drop_column("voice_call_status")

    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.drop_column("voice_call_max_attempts")
        batch_op.drop_column("voice_call_retry_gap_days")
        batch_op.drop_column("voice_call_delay_days")
        batch_op.drop_column("voice_call_enabled")
