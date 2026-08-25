"""Add password_reset_tokens — forgot/reset password flow.

Revision ID: 0009_password_reset_tokens
Revises: 0008_user_last_login
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_password_reset_tokens"
down_revision = "0008_user_last_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("token", sa.Uuid(), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
