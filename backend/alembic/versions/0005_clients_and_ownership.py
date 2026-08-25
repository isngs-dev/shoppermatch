"""Add clients table + client_id ownership on users/campaigns (Client Portal).

Backfills one Client row per distinct existing campaigns.client_name, wires
campaigns.client_id to it, and seeds one demo client-portal login so the
Client Portal has something to log into out of the box. Nothing existing is
deleted or renamed — client_name stays exactly as-is everywhere it's already
used; client_id is purely an additive access-control join.

Revision ID: 0005_clients_and_ownership
Revises: 0004_campaign_requirements
Create Date: 2026-08-14
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0005_clients_and_ownership"
down_revision = "0004_campaign_requirements"
branch_labels = None
depends_on = None

DEMO_CLIENT_USER_EMAIL = "client@nike-demo.example"
DEMO_CLIENT_USER_NAME = "Nike Brand Team"
DEMO_CLIENT_USER_PASSWORD = "client-demo-2026"
DEMO_CLIENT_COMPANY = "Nike"


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False, unique=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_users_client_id", ["client_id"])

    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_campaigns_client_id", ["client_id"])

    # ---- Backfill: one Client row per distinct existing client_name ---- #
    clients_table = sa.table(
        "clients",
        sa.column("id", sa.Uuid()),
        sa.column("company_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    campaigns_table = sa.table(
        "campaigns",
        sa.column("id", sa.Uuid()),
        sa.column("client_name", sa.String()),
        sa.column("client_id", sa.Uuid()),
    )

    now = sa.func.now()
    distinct_names = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT DISTINCT client_name FROM campaigns WHERE client_name IS NOT NULL")
        ).fetchall()
    ]

    name_to_id: dict[str, uuid.UUID] = {}
    for name in distinct_names:
        client_id = uuid.uuid4()
        name_to_id[name] = client_id
        bind.execute(
            clients_table.insert().values(
                id=client_id, company_name=name, status="active", created_at=sa.func.now()
            )
        )

    for name, client_id in name_to_id.items():
        bind.execute(
            campaigns_table.update()
            .where(campaigns_table.c.client_name == name)
            .values(client_id=client_id)
        )

    # ---- Seed one demo client-portal login, tied to the Nike client if it
    # exists in this dataset (falls back to the first client otherwise) ---- #
    demo_client_id = name_to_id.get(DEMO_CLIENT_COMPANY) or next(iter(name_to_id.values()), None)
    if demo_client_id is not None:
        from app.security import hash_password

        users_table = sa.table(
            "users",
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            sa.column("email", sa.String()),
            sa.column("role", sa.String()),
            sa.column("password_hash", sa.String()),
            sa.column("client_id", sa.Uuid()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        existing = bind.execute(
            sa.text("SELECT id FROM users WHERE email = :email"),
            {"email": DEMO_CLIENT_USER_EMAIL},
        ).fetchone()
        if existing is None:
            bind.execute(
                users_table.insert().values(
                    id=uuid.uuid4(),
                    name=DEMO_CLIENT_USER_NAME,
                    email=DEMO_CLIENT_USER_EMAIL,
                    role="client",
                    password_hash=hash_password(DEMO_CLIENT_USER_PASSWORD),
                    client_id=demo_client_id,
                    created_at=sa.func.now(),
                )
            )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE role = 'client'"))
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_index("ix_campaigns_client_id")
        batch_op.drop_column("client_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_client_id")
        batch_op.drop_column("client_id")
    op.drop_table("clients")
