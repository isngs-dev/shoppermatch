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
    UniqueConstraint,
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
# Clients (brands ISN runs mystery-shopping campaigns for — the Client Portal
# scopes every query to one row here via User.client_id / Campaign.client_id).
# --------------------------------------------------------------------------- #
class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Users (ISN admins/operators, role="admin"; client-portal logins, role="client")
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(50), default="admin")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NULL for admin users; required (enforced at the API layer, not a DB
    # constraint, since admins legitimately have none) for role="client" —
    # every /api/client/* query filters through this to the owning Client.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client: Mapped["Client | None"] = relationship(lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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

    # ---- Extended profile fields (migration 0002) ----
    # Added via an Alembic ALTER TABLE rather than recreated, since the
    # `shoppers` table already has live rows. All nullable/defaulted so
    # existing rows stay valid with no backfill required.
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skills: Mapped[list] = mapped_column(json_col(), default=list)
    experience_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    years_experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_locations: Mapped[list] = mapped_column(json_col(), default=list)
    preferred_categories: Mapped[list] = mapped_column(json_col(), default=list)
    languages: Mapped[list] = mapped_column(json_col(), default=list)
    certifications: Mapped[list] = mapped_column(json_col(), default=list)
    previous_clients: Mapped[list] = mapped_column(json_col(), default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # ---- Sync identity (migration 0003) ----
    # `source` already existed (free-text label like "SASSIE"/"Referral");
    # `external_id` is new — the pair (source, external_id) is how
    # synchronization upserts without creating duplicates on repeated runs.
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)


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

    # ---- Sync identity (migration 0003) ----
    # "demo" for the existing seeded dataset, "sassie" for anything created
    # by SASSIE synchronization — the two coexist and are never mixed.
    source: Mapped[str] = mapped_column(String(30), default="demo")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # ---- AI requirement parsing (migration 0004) ----
    # Raw admin-entered natural-language requirement text and the structured
    # fields extracted from it (services/ai/requirement_parser.py). Both
    # nullable — most existing campaigns were never given one.
    requirements_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_requirements: Mapped[dict | None] = mapped_column(json_col(), nullable=True)

    # ---- Client ownership (migration 0005) ----
    # Backfilled from the pre-existing free-text `client_name` at migration
    # time (one Client row per distinct name) — client_name itself is left
    # in place and keeps working everywhere it's already used (UI labels,
    # email variables, matching); client_id is purely the new access-control
    # join, never a second source of truth for the display name.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

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

    # ---- Sync identity (migration 0003) ----
    source: Mapped[str] = mapped_column(String(30), default="demo")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # ---- Over-selection control (migration 0010) ----
    # Off by default: selecting/inviting more shoppers than required_shoppers
    # is blocked. An admin/client can explicitly flip this per shop when they
    # want backup candidates in the pipeline (spec: "Define whether clients
    # can select more than the required number and under what configuration").
    allow_over_selection: Mapped[bool] = mapped_column(Boolean, default=False)

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

    # ---- Email automation (migration 0007) ----
    # Set only for invitations generated by the automation engine
    # (services/automation.py) as one step of a multi-step sequence; NULL for
    # everything created through the manual Outreach composer. Reusing
    # Invitation (rather than a parallel table) means every existing
    # tracking/webhook/outbox mechanism works on automation-sent emails with
    # zero changes. The unique constraint below is the DB-level guarantee
    # that a given automation step is never sent twice to the same shopper.
    automation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_automations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    automation_step: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ---- Assignment-page visit (migration 0006) ----
    # Distinct from clicked_at on purpose: CLICKED means the email link/CTA
    # was followed; VISITED means the assignment landing page itself actually
    # loaded (GET /api/public/invitations/{token}) — see services/tracking.py
    # for why these are never merged into one generic "engaged" event.
    visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    automation: Mapped["EmailAutomation | None"] = relationship()
    events: Mapped[list["InvitationEvent"]] = relationship(
        back_populates="invitation",
        cascade="all, delete-orphan",
        order_by="InvitationEvent.event_timestamp",
    )
    email_job: Mapped["EmailJob | None"] = relationship(
        back_populates="invitation", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        # NULLs (non-automation invitations) never collide under a unique
        # constraint on either SQLite or Postgres — this only bites when an
        # automation step is about to be sent a second time for the same
        # shopper.
        UniqueConstraint(
            "automation_id", "shopper_id", "automation_step", name="uq_invitation_automation_step"
        ),
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
# Integration configs (SASSIE, Email, SMS, Google Maps, AI) — non-secret
# fields live in `configuration`; secrets live in `secret_config` and that
# column is NEVER included in any API response (see serializers.integration_out).
# --------------------------------------------------------------------------- #
class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # sassie|email|sms|maps|ai
    display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="configuration_required")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    configuration: Mapped[dict] = mapped_column(json_col(), default=dict)  # non-secret fields only
    secret_config: Mapped[dict] = mapped_column(json_col(), default=dict)  # never serialized to API
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- #
# Synchronization history (one row per SASSIE sync run)
# --------------------------------------------------------------------------- #
class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")  # running|success|partial|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaigns_fetched: Mapped[int] = mapped_column(Integer, default=0)
    campaigns_created: Mapped[int] = mapped_column(Integer, default=0)
    campaigns_updated: Mapped[int] = mapped_column(Integer, default=0)
    shops_fetched: Mapped[int] = mapped_column(Integer, default=0)
    shops_created: Mapped[int] = mapped_column(Integer, default=0)
    shops_updated: Mapped[int] = mapped_column(Integer, default=0)
    shoppers_fetched: Mapped[int] = mapped_column(Integer, default=0)
    shoppers_created: Mapped[int] = mapped_column(Integer, default=0)
    shoppers_updated: Mapped[int] = mapped_column(Integer, default=0)

    errors: Mapped[list] = mapped_column(json_col(), default=list)  # short strings, not raw payloads
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
# Email automation (migration 0007) — a client-configured 3-step outreach
# sequence (Initial Invitation -> wait -> Reminder -> wait -> Final Reminder)
# for a set of shoppers against one campaign+shop. Each step's actual send is
# a normal Invitation row (automation_id/automation_step set) so the entire
# existing SendGrid/outbox/tracking/webhook pipeline is reused unchanged —
# this table only owns the sequencing/state machine, never delivery itself.
# --------------------------------------------------------------------------- #
class EmailAutomation(Base):
    __tablename__ = "email_automations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    # draft -> scheduled|active -> paused (resumable) -> stopped (terminal) -> completed (terminal)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)

    step1_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_templates.id"), nullable=True)
    step2_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_templates.id"), nullable=True)
    step3_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_templates.id"), nullable=True)

    wait_days: Mapped[int] = mapped_column(Integer, default=2)
    max_steps: Mapped[int] = mapped_column(Integer, default=3)

    # Batch emailing: NULL (default) sends every selected shopper's step 1
    # immediately on Start, same as always. Set batch_size to instead
    # release shoppers in waves of that size, `wait_days` apart (the same
    # cadence already used for per-shopper step advancement), for up to
    # `total_iterations` waves — anyone beyond batch_size * total_iterations
    # stays queued but is never sent. Each shopper's own step 1/2/3 reminder
    # sequence then proceeds independently from whenever their wave sent.
    batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_iterations: Mapped[int] = mapped_column(Integer, default=1)

    # NULL = start immediately on /start. Set = don't send anything before
    # this instant (upcoming-campaign pre-configuration, spec section 13).
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str] = mapped_column(String(255), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    campaign: Mapped["Campaign"] = relationship()
    shop: Mapped["Shop"] = relationship()
    step1_template: Mapped["EmailTemplate | None"] = relationship(foreign_keys=[step1_template_id])
    step2_template: Mapped["EmailTemplate | None"] = relationship(foreign_keys=[step2_template_id])
    step3_template: Mapped["EmailTemplate | None"] = relationship(foreign_keys=[step3_template_id])
    shopper_states: Mapped[list["ShopperAutomationState"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )


class AutomationStatus:
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


# --------------------------------------------------------------------------- #
# Per-shopper automation progress — the engine advances (or stops) each row
# completely independently, so one shopper's activity never affects another
# (spec section 12).
# --------------------------------------------------------------------------- #
class ShopperAutomationState(Base):
    __tablename__ = "shopper_automation_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_automations.id", ondelete="CASCADE"), index=True
    )
    shopper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shoppers.id", ondelete="CASCADE"), index=True
    )

    current_step: Mapped[int] = mapped_column(Integer, default=0)  # 0 = nothing sent yet
    # pending (queued, not yet started) -> active (mid-sequence) -> one of the
    # completed_* terminal states, or stopped (client-initiated).
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    automation: Mapped["EmailAutomation"] = relationship(back_populates="shopper_states")
    shopper: Mapped["Shopper"] = relationship()

    __table_args__ = (
        UniqueConstraint("automation_id", "shopper_id", name="uq_automation_shopper"),
    )


class ShopperAutomationStatus:
    PENDING = "pending"
    ACTIVE = "active"
    STOPPED = "stopped"
    COMPLETED_RESPONSE = "completed_response"      # accepted or declined
    COMPLETED_INTERACTION = "completed_interaction"  # clicked/visited, no response yet
    COMPLETED_NO_RESPONSE = "completed_no_response"  # exhausted all steps, nothing
    COMPLETED_BOUNCED = "completed_bounced"
    COMPLETED_FAILED = "completed_failed"  # provider permanently failed to send


# --------------------------------------------------------------------------- #
# Password reset tokens (forgot/reset password flow). Deliberately a
# separate table rather than columns on User — a token is short-lived,
# single-use, and irrelevant to the user's steady-state row.
# --------------------------------------------------------------------------- #
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[uuid.UUID] = mapped_column(Uuid(), unique=True, index=True, default=uuid.uuid4)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()


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
    ASSIGNMENT_VISITED = "assignment_visited"
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
    VISITED = "visited"
    ACCEPTED = "accepted"
    DECLINED = "declined"

    # Ordered ranking used so status only ever moves forward.
    ORDER = {
        CREATED: 0,
        SENT: 1,
        DELIVERED: 2,
        OPENED: 3,
        CLICKED: 4,
        VISITED: 5,
        ACCEPTED: 6,
        DECLINED: 6,
    }


class IntegrationStatus:
    CONNECTED = "connected"
    DEMO = "demo"  # working, but backed by the demo adapter, not a real external call
    DISCONNECTED = "disconnected"
    CONFIGURATION_REQUIRED = "configuration_required"
    ERROR = "error"
    TESTING = "testing"
