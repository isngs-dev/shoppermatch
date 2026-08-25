"""Add shops.allow_over_selection — over-selection control.

Revision ID: 0010_shop_over_selection
Revises: 0009_password_reset_tokens
Create Date: 2026-08-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_shop_over_selection"
down_revision = "0009_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("allow_over_selection", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("shops", "allow_over_selection")
