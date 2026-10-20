"""Request and response models for account authentication."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.pydantic import Email, Username


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(AuthRequest):
    username: Username
    email: Email
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value


class LoginIn(AuthRequest):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    status: str
    created_at: datetime

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "UserOut":
        return cls(
            id=str(document["_id"]),
            username=document["username"],
            email=document["email"],
            display_name=document.get("display_name", document["username"]),
            status=document.get("status", "active"),
            created_at=document["created_at"],
        )


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


__all__ = ["LoginIn", "RegisterIn", "TokenOut", "UserOut"]
