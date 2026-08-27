"""Campaign-wide email automations: email_automations.shop_id becomes
nullable (NULL = spans every shop in the campaign), and
shopper_automation_states gains its own shop_id so each shopper's actual
Invitation still resolves to a real shop even when the automation itself
isn't scoped to one.

Revision ID: 0012_campaign_wide_automations
Revises: 0011_batch_automations
Create Date: 2026-08-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_campaign_wide_automations"
down_revision = "0011_batch_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.alter_column("shop_id", existing_type=sa.Uuid(), nullable=True)

    with op.batch_alter_table("shopper_automation_states") as batch_op:
        batch_op.add_column(sa.Column("shop_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shopper_automation_states_shop_id", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index("ix_shopper_automation_states_shop_id", "shopper_automation_states", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_shopper_automation_states_shop_id", table_name="shopper_automation_states")
    with op.batch_alter_table("shopper_automation_states") as batch_op:
        batch_op.drop_constraint("fk_shopper_automation_states_shop_id", type_="foreignkey")
        batch_op.drop_column("shop_id")
    with op.batch_alter_table("email_automations") as batch_op:
        batch_op.alter_column("shop_id", existing_type=sa.Uuid(), nullable=False)
