"""Extend shoppers with richer profile fields for semantic matching.

Adds gender, age, pincode, skills, experience_description, years_experience,
preferred_distance_km, preferred_locations, preferred_categories, languages,
certifications, previous_clients, updated_at.

All nullable or defaulted — existing rows remain valid, no backfill needed.

Revision ID: 0002_shopper_profile_fields
Revises: 0001_initial
Create Date: 2026-08-12
"""
import sqlalchemy as sa
from alembic import op

from app.models import json_col

revision = "0002_shopper_profile_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shoppers") as batch_op:
        batch_op.add_column(sa.Column("gender", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("age", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pincode", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("skills", json_col(), nullable=True))
        batch_op.add_column(sa.Column("experience_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("years_experience", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("preferred_distance_km", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("preferred_locations", json_col(), nullable=True))
        batch_op.add_column(sa.Column("preferred_categories", json_col(), nullable=True))
        batch_op.add_column(sa.Column("languages", json_col(), nullable=True))
        batch_op.add_column(sa.Column("certifications", json_col(), nullable=True))
        batch_op.add_column(sa.Column("previous_clients", json_col(), nullable=True))
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("shoppers") as batch_op:
        for col in (
            "gender", "age", "pincode", "skills", "experience_description",
            "years_experience", "preferred_distance_km", "preferred_locations",
            "preferred_categories", "languages", "certifications",
            "previous_clients", "updated_at",
        ):
            batch_op.drop_column(col)
