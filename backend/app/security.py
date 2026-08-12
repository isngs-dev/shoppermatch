"""Authentication & token helpers.

Implemented with the Python standard library only (no bcrypt/pyjwt) so the demo
installs cleanly on any platform:

* Passwords are hashed with PBKDF2-HMAC-SHA256 (salted, 200k iterations).
* Access tokens are compact, HMAC-SHA256 signed JSON (JWT-like) with an expiry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from .config import settings

_PBKDF2_ITERATIONS = 200_000


# ------------------------------ Passwords ------------------------------ #
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ------------------------------ Tokens ------------------------------ #
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(message: bytes) -> str:
    sig = hmac.new(settings.secret_key.encode(), message, hashlib.sha256).digest()
    return _b64url_encode(sig)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
    }
    if extra:
        payload.update(extra)
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _sign(body.encode())
    return f"{body}.{signature}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Return the token payload if the signature is valid and it has not expired."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None
    expected = _sign(body.encode())
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
