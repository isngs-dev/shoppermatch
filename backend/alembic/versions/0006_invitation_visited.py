"""Add invitations.visited_at — distinct from clicked_at (spec: "the platform
must distinguish EMAIL OPEN from LINK CLICK from ASSIGNMENT VISIT"). Nullable,
existing invitations are unaffected.

Revision ID: 0006_invitation_visited
Revises: 0005_clients_and_ownership
Create Date: 2026-08-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_invitation_visited"
down_revision = "0005_clients_and_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.add_column(sa.Column("visited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.drop_column("visited_at")
