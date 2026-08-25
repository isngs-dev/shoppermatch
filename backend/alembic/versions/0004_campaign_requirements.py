"""Add requirements_text / parsed_requirements to campaigns (AI Campaign
Requirement Parser). Nullable — existing campaigns are unaffected.

Revision ID: 0004_campaign_requirements
Revises: 0003_sync_identity_fields
Create Date: 2026-08-12
"""
import sqlalchemy as sa
from alembic import op

from app.models import json_col

revision = "0004_campaign_requirements"
down_revision = "0003_sync_identity_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("requirements_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("parsed_requirements", json_col(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("parsed_requirements")
        batch_op.drop_column("requirements_text")
