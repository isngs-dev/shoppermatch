"""Add shop_bonuses table — client-funded bonus money for unfilled shops
(conceptual/demo, see models.py::ShopBonus). One row per shop; ShopperMatch
never processes the actual payment, only tracks the pledge and the shopper
it was eventually awarded to.

Revision ID: 0016_shop_bonuses
Revises: 0015_client_social_accounts
Create Date: 2026-09-01
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0016_shop_bonuses"
down_revision = "0015_client_social_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shop_bonuses",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("shop_id", sa.Uuid(), sa.ForeignKey("shops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "awarded_invitation_id", sa.Uuid(), sa.ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("awarded_shopper_name", sa.String(255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("shop_id", name="uq_shop_bonus_shop"),
    )
    op.create_index("ix_shop_bonuses_shop_id", "shop_bonuses", ["shop_id"])
    op.create_index("ix_shop_bonuses_campaign_id", "shop_bonuses", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_shop_bonuses_campaign_id", table_name="shop_bonuses")
    op.drop_index("ix_shop_bonuses_shop_id", table_name="shop_bonuses")
    op.drop_table("shop_bonuses")
