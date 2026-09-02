"""Encryption at rest for OAuth tokens (Social Media Automation).

No encryption utility existed anywhere in this codebase before — every other
secret (SendGrid/OpenAI API keys, SMTP password) is a server-side env var,
never a database column. Real OAuth tokens are different: they're minted at
runtime per client and must live in the database, so they need to be
encrypted there. Fernet (symmetric, authenticated) via the `cryptography`
package, already a dependency (routers/webhooks.py uses it for SendGrid
webhook signature verification).
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from ..config import settings


@lru_cache
def _fernet():
    from cryptography.fernet import Fernet

    key = settings.social_token_encryption_key
    if not key:
        # Local/demo fallback only — derive a stable key from secret_key so
        # tokens still round-trip without a separate env var to set up. In
        # production, set SOCIAL_TOKEN_ENCRYPTION_KEY explicitly: rotating
        # secret_key would otherwise silently make every stored token
        # undecryptable.
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    elif isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def encrypt_token(plaintext: str) -> str:
    """Returns a Fernet ciphertext string safe to store in a Text column."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    """Inverse of encrypt_token. Raises cryptography.fernet.InvalidToken if
    the ciphertext is malformed or was encrypted under a different key
    (e.g. SOCIAL_TOKEN_ENCRYPTION_KEY rotated) — callers should treat that
    as "reconnect required", never crash the request."""
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
