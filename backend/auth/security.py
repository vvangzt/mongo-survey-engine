"""Password hashing, JWT creation and token extraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from bson import ObjectId
from fastapi import Request
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from ..config import get_settings

_password_hash = PasswordHash.recommended()
_DUMMY_HASH = _password_hash.hash("not-a-real-account-password")


class AuthenticationError(Exception):
    """Credential or token is missing, invalid or expired."""


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def verify_dummy_password(password: str) -> None:
    """Spend roughly the same time when the account does not exist."""

    _password_hash.verify(password, _DUMMY_HASH)


def create_access_token(user_id: ObjectId) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> ObjectId:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except InvalidTokenError as exc:
        raise AuthenticationError("invalid or expired token") from exc
    if payload.get("type") != "access":
        raise AuthenticationError("invalid token type")
    raw_subject = payload.get("sub")
    if not isinstance(raw_subject, str):
        raise AuthenticationError("token subject is missing")
    try:
        return ObjectId(raw_subject)
    except Exception as exc:
        raise AuthenticationError("token subject is invalid") from exc


def extract_access_token(request: Request) -> str | None:
    """Read Authorization: Bearer first, then the HttpOnly cookie."""

    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip()
    settings = get_settings()
    cookie = request.cookies.get(settings.access_token_cookie)
    return cookie or None


def token_payload_summary(token: str) -> dict[str, Any]:
    """Test/debug helper that returns decoded claims without trusting them."""

    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


__all__ = [
    "AuthenticationError",
    "create_access_token",
    "decode_access_token",
    "extract_access_token",
    "hash_password",
    "token_payload_summary",
    "verify_dummy_password",
    "verify_password",
]
