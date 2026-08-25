"""Shared FastAPI dependencies (auth)."""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from .models import User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False, description="ISN admin bearer token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.role == "client" and user.client is not None and user.client.status != "active":
        # Blocks every already-issued token the instant an account is
        # deactivated/deleted, not just future logins — tokens are stateless
        # JWTs, so this DB check on every request is what actually revokes access.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated.")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Gate for every ISN-operational endpoint (campaigns, shops, shoppers,
    AI, outreach, tracking analytics, integrations, audit logs). Enforced
    server-side — a client-role token is rejected here regardless of what
    the frontend does or doesn't render."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_client(user: User = Depends(get_current_user)) -> User:
    """Gate for every /api/client/* endpoint. Requires role == "client" AND
    a non-null client_id — every client-portal query then filters through
    that id, so one client can never see another client's data."""
    if user.role != "client" or user.client_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client access required")
    return user


async def require_operator(user: User = Depends(get_current_user)) -> User:
    """Gate for the operational modules (campaigns, shops, shoppers,
    recommendations, outreach, AI matching) now shared by both portals:
    ISN Admin (unrestricted) and Client (tenant-scoped to their own
    client_id). Every route using this dependency MUST additionally enforce
    campaign ownership via `services/tenancy.py::enforce_campaign_access`
    (or an equivalent join filter) when `user.role == "client"` — this
    dependency only proves "logged in as admin or client," not "owns this
    campaign."""
    if user.role == "admin":
        return user
    if user.role == "client" and user.client_id is not None:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
