import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: uuid.UUID) -> str:
    now = _now()
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_ttl_seconds)).timestamp()),
        "jti": secrets.token_urlsafe(8),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    # Бросает jwt.ExpiredSignatureError / jwt.PyJWTError — ловим в deps.
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_opaque_token() -> str:
    """Непрозрачный случайный токен (refresh / reset / verify)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return _now() + timedelta(seconds=settings.refresh_ttl_seconds)
