"""Shopper chatbot actions: opt-out flags, client confidentiality, interests,
escalations and follow-ups.

Revision ID: 0022_chatbot_shopper_actions
Revises: 0021_chatbot
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_chatbot_shopper_actions"
down_revision = "0021_chatbot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shoppers") as b:
        b.add_column(sa.Column("opted_out_email", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("opted_out_phone", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("campaigns") as b:
        b.add_column(sa.Column("client_confidential", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "shopper_interests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("shopper_id", sa.Uuid(), sa.ForeignKey("shoppers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("chat_conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("preferred_date", sa.Date(), nullable=False),
        sa.Column("preferred_time", sa.String(40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(60), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chat_escalations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("chat_conversations.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("shopper_id", sa.Uuid(), sa.ForeignKey("shoppers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, index=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("new_date", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shopper_followups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("shopper_id", sa.Uuid(), sa.ForeignKey("shoppers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), sa.ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shopper_followups")
    op.drop_table("chat_escalations")
    op.drop_table("shopper_interests")
    with op.batch_alter_table("campaigns") as b:
        b.drop_column("client_confidential")
    with op.batch_alter_table("shoppers") as b:
        b.drop_column("opted_out_at")
        b.drop_column("opted_out_phone")
        b.drop_column("opted_out_email")
