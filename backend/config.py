"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_db: str
    jwt_secret: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    access_token_cookie: str
    cookie_secure: bool
    auto_create_indexes: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mongodb_uri=os.getenv(
                "MONGODB_URI", "mongodb://localhost:27017"
            ),
            mongodb_db=os.getenv("MONGODB_DB", "questionnaire"),
            jwt_secret=os.getenv(
                "JWT_SECRET", "dev-only-change-this-secret-0123456789abcdef"
            ),
            jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
            access_token_expire_minutes=int(
                os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
            ),
            access_token_cookie=os.getenv(
                "ACCESS_TOKEN_COOKIE", "survey_access_token"
            ),
            cookie_secure=_env_bool("COOKIE_SECURE", False),
            auto_create_indexes=_env_bool("AUTO_CREATE_INDEXES", True),
        )


def get_settings() -> Settings:
    """Build settings on demand so tests can set environment variables."""

    return Settings.from_env()
