"""Pydantic request/response models used for validation and OpenAPI docs."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


# --------------------------- Auth --------------------------- #
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------- Invitations --------------------------- #
class InvitationCreateRequest(BaseModel):
    campaign_id: str
    shop_id: str
    shopper_id: str
    template: Literal["standard", "reminder", "premium"] = "standard"
    subject: Optional[str] = Field(default=None, max_length=300)
    recipient_email: Optional[EmailStr] = None
    auto_send: bool = True
    utm_source: str = "isn"
    utm_medium: str = "email"
    utm_campaign: Optional[str] = None
    utm_content: str = "invitation"
    # Composer overrides: when both are provided, the invitation is rendered
    # from this admin-edited subject/body (with {{variable}} substitution)
    # instead of the default generated template. Stored in a separate
    # EmailComposition row — see models.py for why.
    custom_subject: Optional[str] = Field(default=None, max_length=500)
    custom_html: Optional[str] = None


class SendTestRequest(BaseModel):
    test_email: EmailStr


class RespondRequest(BaseModel):
    response: Literal["accepted", "declined"]
    note: Optional[str] = Field(default=None, max_length=1000)


class SimulateRequest(BaseModel):
    """Drives the demo 'Simulate ...' buttons against real backend endpoints."""
    action: Literal["send", "deliver", "open", "click", "accept", "decline"]
