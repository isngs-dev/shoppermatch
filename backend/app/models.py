"""SQLAlchemy 2.x ORM models for ShopperMatch.AI.

Design notes
------------
* Primary keys are UUIDs (`sqlalchemy.Uuid`) — native `uuid` on Postgres,
  CHAR(32) on SQLite — so no raw integer database IDs are ever exposed publicly.
* `invitation_events.metadata` uses JSONB on Postgres and JSON on SQLite via a
  type variant. The Python attribute is `event_metadata` because `metadata` is a
  reserved name on the declarative base.
* All timestamps are timezone-aware UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_col():
    """A JSON column that upgrades to JSONB on PostgreSQL."""
    return JSON().with_variant(JSONB(), "postgresql")


# --------------------------------------------------------------------------- #
# Users (ISN admins / operators)
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(50), default="admin")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Shoppers (mystery shoppers available for assignment)
# --------------------------------------------------------------------------- #
class Shopper(Base):
    __tablename__ = "shoppers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    shopper_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    categories: Mapped[list] = mapped_column(json_col(), default=list)
    availability_status: Mapped[str] = mapped_column(String(30), default="available")
    source: Mapped[str] = mapped_column(String(60), default="SASSIE")
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    previous_assignments: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Campaigns (a client engagement bundling many shops)
# --------------------------------------------------------------------------- #
class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    client_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    total_shops: Mapped[int] = mapped_column(Integer, default=0)
    completed_shops: Mapped[int] = mapped_column(Integer, default=0)
    remaining_shops: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shops: Mapped[list["Shop"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# Shops (a physical location that needs to be shopped)
# --------------------------------------------------------------------------- #
class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    shop_name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_shoppers: Mapped[int] = mapped_column(Integer, default=1)
    compensation: Mapped[int] = mapped_column(Integer, default=0)  # whole currency units
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    visit_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visit_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")

    campaign: Mapped["Campaign"] = relationship(back_populates="shops")


# --------------------------------------------------------------------------- #
# Invitations (one outreach message to one shopper for one shop)
# --------------------------------------------------------------------------- #
class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    shopper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shoppers.id", ondelete="CASCADE"), index=True
    )

    # The unique, unguessable public tracking token. Maps to exactly one invite.
    tracking_token: Mapped[uuid.UUID] = mapped_column(
        Uuid(), unique=True, index=True, default=uuid.uuid4
    )

    # Short human-friendly reference, e.g. INV-0007
    reference: Mapped[str] = mapped_column(String(30), index=True)

    email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str | None] = mapped_column(String(30), nullable=True)  # accepted|declined

    # Attribution / UTM
    source: Mapped[str] = mapped_column(String(60), default="ISN Outreach")
    utm_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped["Campaign"] = relationship()
    shop: Mapped["Shop"] = relationship()
    shopper: Mapped["Shopper"] = relationship()
    events: Mapped[list["InvitationEvent"]] = relationship(
        back_populates="invitation",
        cascade="all, delete-orphan",
        order_by="InvitationEvent.event_timestamp",
    )
    email_job: Mapped["EmailJob | None"] = relationship(
        back_populates="invitation", cascade="all, delete-orphan", uselist=False
    )


# --------------------------------------------------------------------------- #
# Invitation events (immutable audit trail of everything that happened)
# --------------------------------------------------------------------------- #
class InvitationEvent(Base):
    __tablename__ = "invitation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invitations.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    # DB column is `metadata`; Python attribute is `event_metadata`.
    event_metadata: Mapped[dict] = mapped_column("metadata", json_col(), default=dict)

    invitation: Mapped["Invitation"] = relationship(back_populates="events")


# --------------------------------------------------------------------------- #
# Email outbox (ShopperMatch-owned queue + provider attempt history)
# --------------------------------------------------------------------------- #
class EmailJob(Base):
    __tablename__ = "email_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invitations.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invitation: Mapped["Invitation"] = relationship(back_populates="email_job")


# --------------------------------------------------------------------------- #
# Email templates (admin-authored, reusable across invitations)
# --------------------------------------------------------------------------- #
class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(500))
    html_body: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- #
# Email composition (the admin-edited subject/body for one invitation).
# A new, separate table rather than new columns on `invitations` — this demo
# runs against an already-seeded SQLite file, and SQLAlchemy's create_all()
# only creates missing tables, it does not ALTER existing ones. Only present
# when the admin composed/edited the email by hand; otherwise the invitation
# falls back to the default rendered template (see services/email.py).
# --------------------------------------------------------------------------- #
class EmailComposition(Base):
    __tablename__ = "email_compositions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invitations.id", ondelete="CASCADE"), unique=True, index=True
    )
    subject_template: Mapped[str] = mapped_column(String(500))
    html_template: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- #
# Audit log (basic security/audit logging for admin actions)
# --------------------------------------------------------------------------- #
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(255), default="system")
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    meta: Mapped[dict] = mapped_column(json_col(), default=dict)


# Event type + status constants (kept in one place for reuse across the app).
class EventType:
    INVITATION_CREATED = "invitation_created"
    EMAIL_QUEUED = "email_queued"
    EMAIL_SENT = "email_sent"
    EMAIL_DELIVERED = "email_delivered"
    EMAIL_OPENED = "email_opened"
    LINK_CLICKED = "link_clicked"
    ASSIGNMENT_ACCEPTED = "assignment_accepted"
    ASSIGNMENT_DECLINED = "assignment_declined"
    EMAIL_BOUNCED = "email_bounced"
    EMAIL_FAILED = "email_failed"
    EMAIL_DEFERRED = "email_deferred"


class InvitationStatus:
    CREATED = "created"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    ACCEPTED = "accepted"
    DECLINED = "declined"

    # Ordered ranking used so status only ever moves forward.
    ORDER = {
        CREATED: 0,
        SENT: 1,
        DELIVERED: 2,
        OPENED: 3,
        CLICKED: 4,
        ACCEPTED: 5,
        DECLINED: 5,
    }
