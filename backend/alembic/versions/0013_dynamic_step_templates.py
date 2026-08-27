"""Add email_automations.step_template_ids — an ordered, arbitrary-length
list of template ids so an automation can run more than 3 steps (most
commonly one distinct email per batch-emailing wave). NULL/absent means
"use the legacy step1/2/3_template_id columns", so every existing
automation keeps working unchanged.

Revision ID: 0013_dynamic_step_templates
Revises: 0012_campaign_wide_automations
Create Date: 2026-08-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_dynamic_step_templates"
down_revision = "0012_campaign_wide_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.add_column(sa.Column("step_template_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.drop_column("step_template_ids")
