"""Account registration and password verification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase

from .schemas import RegisterIn
from .security import (
    hash_password,
    verify_dummy_password,
    verify_password,
)


class UsernameTakenError(Exception):
    pass


class EmailTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AccountDisabledError(Exception):
    pass


class AuthService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._users = db["users"]

    async def register(self, payload: RegisterIn) -> dict[str, Any]:
        existing = await self._users.find_one(
            {
                "$or": [
                    {"username": payload.username},
                    {"email": payload.email},
                ]
            },
            {"username": 1, "email": 1},
        )
        if existing:
            if existing.get("username") == payload.username:
                raise UsernameTakenError("username is already registered")
            raise EmailTakenError("email is already registered")

        now = datetime.now(timezone.utc)
        display_name = (
            payload.display_name.strip()
            if payload.display_name and payload.display_name.strip()
            else payload.username
        )
        document = {
            "_id": ObjectId(),
            "schema_version": 1,
            "username": payload.username,
            "email": payload.email,
            "password_hash": hash_password(payload.password),
            "display_name": display_name,
            "status": "active",
            "last_login_at": now,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self._users.insert_one(document)
        except DuplicateKeyError as exc:
            # A concurrent registration may have won after the pre-check.
            existing = await self._users.find_one(
                {
                    "$or": [
                        {"username": payload.username},
                        {"email": payload.email},
                    ]
                },
                {"username": 1},
            )
            if existing and existing.get("username") == payload.username:
                raise UsernameTakenError("username is already registered") from exc
            raise EmailTakenError("email is already registered") from exc
        return document

    async def authenticate(
        self, username: str, password: str
    ) -> dict[str, Any]:
        user = await self._users.find_one({"username": username})
        if user is None:
            verify_dummy_password(password)
            raise InvalidCredentialsError("invalid username or password")
        if not verify_password(password, user["password_hash"]):
            raise InvalidCredentialsError("invalid username or password")
        if user.get("status") != "active":
            raise AccountDisabledError("account is disabled")

        now = datetime.now(timezone.utc)
        await self._users.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_login_at": now, "updated_at": now}},
        )
        user["last_login_at"] = now
        return user

    async def get_user(self, user_id: ObjectId) -> dict[str, Any] | None:
        return await self._users.find_one(
            {"_id": user_id, "status": "active"}
        )


__all__ = [
    "AccountDisabledError",
    "AuthService",
    "EmailTakenError",
    "InvalidCredentialsError",
    "UsernameTakenError",
]
