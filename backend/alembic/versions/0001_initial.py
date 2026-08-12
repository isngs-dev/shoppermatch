"""Baseline schema — materialises the current ORM models.

This baseline creates every table from ``Base.metadata`` so it stays perfectly
in sync with the models. Subsequent schema changes should be generated with
``alembic revision --autogenerate -m "..."``.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-11
"""
from alembic import op

from app import models  # noqa: F401  (register models on metadata)
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
