"""FastAPI dependencies for database access and authentication."""

from __future__ import annotations

from typing import Annotated

from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from pymongo.asynchronous.database import AsyncDatabase

from .auth.security import (
    AuthenticationError,
    decode_access_token,
    extract_access_token,
)
from .questions.service import QuestionLibraryService
from .stats.cross import CrossSurveyStatsService
from .stats.service import StatsService
from .surveys.service import SurveyService


async def get_db(request: Request) -> AsyncDatabase:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="database is not initialised",
        )
    return db


async def _user_id_from_token(
    db: AsyncDatabase, token: str
) -> ObjectId:
    try:
        user_id = decode_access_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await db["users"].find_one(
        {"_id": user_id, "status": "active"}, {"_id": 1}
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


async def get_current_user_id(
    request: Request,
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> ObjectId:
    token = extract_access_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _user_id_from_token(db, token)


async def get_optional_current_user_id(
    request: Request,
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> ObjectId | None:
    token = extract_access_token(request)
    if token is None:
        return None
    return await _user_id_from_token(db, token)


def get_stats_service(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> StatsService:
    return StatsService(db)


def get_survey_service(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> SurveyService:
    return SurveyService(db)


def get_question_service(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> QuestionLibraryService:
    return QuestionLibraryService(db)


def get_cross_stats_service(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> CrossSurveyStatsService:
    return CrossSurveyStatsService(db)


DatabaseDep = Annotated[AsyncDatabase, Depends(get_db)]
CurrentUserIdDep = Annotated[ObjectId, Depends(get_current_user_id)]
OptionalCurrentUserIdDep = Annotated[
    ObjectId | None, Depends(get_optional_current_user_id)
]
StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]
SurveyServiceDep = Annotated[SurveyService, Depends(get_survey_service)]
QuestionServiceDep = Annotated[
    QuestionLibraryService, Depends(get_question_service)
]
CrossSurveyStatsDep = Annotated[
    CrossSurveyStatsService, Depends(get_cross_stats_service)
]


__all__ = [
    "CrossSurveyStatsDep",
    "CurrentUserIdDep",
    "DatabaseDep",
    "OptionalCurrentUserIdDep",
    "QuestionServiceDep",
    "StatsServiceDep",
    "SurveyServiceDep",
    "get_cross_stats_service",
    "get_current_user_id",
    "get_db",
    "get_optional_current_user_id",
    "get_question_service",
    "get_stats_service",
    "get_survey_service",
]
