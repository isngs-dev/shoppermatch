"""Add users.last_login_at — Admin User Management (spec section 25) needs a
real "last login" value per client user instead of a fabricated one.
Nullable; set on each successful /api/auth/login.

Revision ID: 0008_user_last_login
Revises: 0007_email_automation
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_user_last_login"
down_revision = "0007_email_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("last_login_at")
