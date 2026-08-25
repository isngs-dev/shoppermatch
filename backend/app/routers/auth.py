"""Authentication endpoints: login, self-service client registration, and
forgot/reset password (real email sent through the same SendGrid pipeline
used for shopper outreach)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import get_current_user
from ..deps import get_current_user
from ..models import Client, PasswordResetToken, User
from ..schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from ..security import create_access_token, hash_password, verify_password
from ..serializers import user_out
from ..services.audit import record_audit
from ..services.email import send_email

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(User).where(User.email == str(body.email).lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user.role == "client" and user.client is not None and user.client.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact your ISN account manager.",
        )
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user_out(user),
    }


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    return user_out(current)


# --------------------------------------------------------------------------- #
# Self-service client registration. Creates a new Client + a role="client"
# User atomically, then logs them straight in (same shape as /login) — the
# new account starts with no campaigns until ISN sets one up for them, same
# as any client onboarded by an admin.
# --------------------------------------------------------------------------- #
@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    email = str(body.email).lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    client = Client(
        company_name=body.company_name.strip(),
        contact_name=body.contact_name.strip(),
        contact_email=email,
        status="active",
    )
    session.add(client)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A client account with this company name already exists.")

    user = User(
        name=body.contact_name.strip(),
        email=email,
        role="client",
        client_id=client.id,
        password_hash=hash_password(body.password),
        last_login_at=datetime.now(timezone.utc),
    )
    user.client = client  # avoid a lazy-load round trip on the relationship below
    session.add(user)
    await session.flush()

    await record_audit(
        session,
        action="client.registered",
        actor=email,
        entity_type="client",
        entity_id=str(client.id),
        summary=f"New client account self-registered: {body.company_name} ({email})",
        meta={"company_name": body.company_name},
    )
    await session.commit()

    token = create_access_token(str(user.id), {"email": user.email, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user_out(user),
    }


# --------------------------------------------------------------------------- #
# Forgot / reset password. Always returns the same generic message whether
# or not the email exists, so this endpoint can't be used to enumerate
# accounts. The actual reset email is sent through the same send_email()
# pipeline services/email.py uses for real shopper outreach — same
# SendGrid config, same delivery guarantees.
# --------------------------------------------------------------------------- #
@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, session: AsyncSession = Depends(get_session)):
    generic = {"message": "If an account with that email exists, a password reset link has been sent."}
    email = str(body.email).lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        return generic

    reset_token = PasswordResetToken(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(reset_token)
    await session.flush()

    reset_url = f"{settings.public_base_url}/reset-password?token={reset_token.token}"
    message = {
        "from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "to": user.email,
        "subject": "Reset your ShopperMatch.AI password",
        "html": (
            f"<p>Hi {user.name},</p>"
            "<p>We received a request to reset your ShopperMatch.AI password. This link expires in 30 minutes.</p>"
            f'<p><a href="{reset_url}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
            'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
            "Reset Password</a></p>"
            "<p>If you didn't request this, you can safely ignore this email — your password won't change.</p>"
            "<p>Thank you,<br/>ShopperMatch.AI Team</p>"
        ),
        "text": f"Reset your ShopperMatch.AI password: {reset_url} (expires in 30 minutes)",
    }
    result = await send_email(message)

    await record_audit(
        session,
        action="auth.password_reset_requested",
        actor=user.email,
        entity_type="user",
        entity_id=str(user.id),
        summary=f"Password reset requested for {user.email}",
        meta={"delivered": result.get("delivered"), "provider": result.get("provider")},
    )
    await session.commit()
    return generic


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, session: AsyncSession = Depends(get_session)):
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    try:
        token_uuid = uuid.UUID(body.token)
    except (ValueError, AttributeError):
        raise invalid

    # Expiry is checked in the query itself (not with a Python-side
    # comparison) — SQLite doesn't round-trip tzinfo on DateTime(timezone=True)
    # columns, so a naive value read back from the DB can't be compared
    # directly against an aware datetime.now(timezone.utc).
    reset_token = (
        await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token_uuid,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at >= datetime.now(timezone.utc),
            )
        )
    ).scalar_one_or_none()
    if reset_token is None:
        raise invalid

    user = await session.get(User, reset_token.user_id)
    if user is None:
        raise invalid

    user.password_hash = hash_password(body.new_password)
    reset_token.used_at = datetime.now(timezone.utc)

    await record_audit(
        session,
        action="auth.password_reset_completed",
        actor=user.email,
        entity_type="user",
        entity_id=str(user.id),
        summary=f"Password reset completed for {user.email}",
    )
    await session.commit()
    return {"message": "Password updated. You can now sign in with your new password."}


# --------------------------------------------------------------------------- #
# Change password while logged in (distinct from forgot/reset above, which is
# for a locked-out user). Works for any role — the client Profile page's
# "Change Password" card and any future admin equivalent both call this.
# --------------------------------------------------------------------------- #
@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    await record_audit(
        session,
        action="auth.password_changed",
        actor=user.email,
        entity_type="user",
        entity_id=str(user.id),
        summary=f"Password changed by {user.email}",
    )
    await session.commit()
    return {"message": "Password updated."}
