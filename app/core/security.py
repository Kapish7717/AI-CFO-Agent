"""Security primitives: password hashing, JWT tokens, and FastAPI auth deps.

Password hashes use PBKDF2-HMAC-SHA256 (600k iterations, random 16-byte salt).
Legacy SHA-256 ``salt:hash`` hashes are still verified transparently so existing
users can log in until their password is next changed.

JWT access tokens carry ``sub`` (user id), ``email`` and ``role`` claims and are
validated via the ``Authorization: Bearer <token>`` header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

logger = logging.getLogger("cfo.security")

PBKDF2_ITERATIONS = 600_000
PBKDF2_PREFIX = "pbkdf2_sha256"
JWT_CLAIMS = ("sub", "email", "role", "full_name")

_bearer_scheme = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a PBKDF2-HMAC-SHA256 hash: ``pbkdf2_sha256$<iters>$<salt>$<digest>``."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash (PBKDF2 or legacy SHA-256)."""
    if not stored_hash:
        return False
    try:
        if stored_hash.startswith(f"{PBKDF2_PREFIX}$"):
            _, iters, salt_hex, digest_b64 = stored_hash.split("$")
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
            )
            return hmac.compare_digest(
                base64.urlsafe_b64encode(digest).decode("ascii"), digest_b64
            )
        # Legacy format: "<salt>:<sha256hex>"
        salt, pwd_hash = stored_hash.split(":", 1)
        candidate = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
        return hmac.compare_digest(candidate, pwd_hash)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(user_id: int, email: str, role: str, full_name: str = "") -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "full_name": full_name,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.JWT_ALGORITHM])


def mask_secret(value: str | None, visible: int = 4) -> str | None:
    """Return a masked version of a secret for API responses (``sk-...abcd``)."""
    if not value:
        return None
    value = str(value)
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}…{value[-visible:]}"


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Return the authenticated user claims (``sub`` is the user id)."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        logger.info("Rejected invalid JWT: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user_id(current: dict = Depends(get_current_user)) -> int:
    """Shorthand dependency that resolves the authenticated user id."""
    return int(current["sub"])