"""Add sync identity fields (source, external_id) to campaigns and shops,
and external_id to shoppers (shoppers already had `source`).

Needed so SASSIE synchronization can upsert by (source, external_id)
without ever duplicating or colliding with the existing demo dataset.

Revision ID: 0003_sync_identity_fields
Revises: 0002_shopper_profile_fields
Create Date: 2026-08-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_sync_identity_fields"
down_revision = "0002_shopper_profile_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(30), nullable=False, server_default="demo"))
        batch_op.add_column(sa.Column("external_id", sa.String(120), nullable=True))
    op.create_index("ix_campaigns_external_id", "campaigns", ["external_id"])

    with op.batch_alter_table("shops") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(30), nullable=False, server_default="demo"))
        batch_op.add_column(sa.Column("external_id", sa.String(120), nullable=True))
    op.create_index("ix_shops_external_id", "shops", ["external_id"])

    with op.batch_alter_table("shoppers") as batch_op:
        batch_op.add_column(sa.Column("external_id", sa.String(120), nullable=True))
    op.create_index("ix_shoppers_external_id", "shoppers", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_shoppers_external_id", table_name="shoppers")
    with op.batch_alter_table("shoppers") as batch_op:
        batch_op.drop_column("external_id")

    op.drop_index("ix_shops_external_id", table_name="shops")
    with op.batch_alter_table("shops") as batch_op:
        batch_op.drop_column("external_id")
        batch_op.drop_column("source")

    op.drop_index("ix_campaigns_external_id", table_name="campaigns")
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("external_id")
        batch_op.drop_column("source")
