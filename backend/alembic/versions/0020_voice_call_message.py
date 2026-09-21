"""AI Voice Call Follow-Up: custom opening message — lets a client set the
exact recorded/scripted line Twilio's TTS reads when the call connects,
instead of the fixed default in services/voice_call_ai.py::opening_line.
NULL keeps today's default behavior unchanged.

Revision ID: 0020_voice_call_message
Revises: 0019_voice_call_followup
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_voice_call_message"
down_revision = "0019_voice_call_followup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.add_column(sa.Column("voice_call_message", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.drop_column("voice_call_message")
