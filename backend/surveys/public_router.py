"""Public, slug-addressable survey fill endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from pymongo.asynchronous.database import AsyncDatabase

from schemas.pydantic import SubmissionValidationError

from ..dependencies import (
    OptionalCurrentUserIdDep,
    get_db,
)
from .http_errors import raise_http_error
from .public_schemas import AdvanceIn, AdvanceOut, PublicSurveyOut
from .public_service import PublicSurveyService
from .schemas import SubmitIn, SubmitOut
from .service import (
    SurveyConflictError,
    SurveyForbiddenError,
    SurveyNotFoundError,
    SurveyUnauthenticatedError,
    SurveyValidationError,
)

router = APIRouter(
    prefix="/api/public/surveys",
    tags=["public-surveys"],
)

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{4,61}[a-z0-9])$"


def get_public_survey_service(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> PublicSurveyService:
    return PublicSurveyService(db)


PublicServiceDep = Annotated[
    PublicSurveyService, Depends(get_public_survey_service)
]

_DOMAIN_ERRORS = (
    SurveyNotFoundError,
    SurveyUnauthenticatedError,
    SurveyForbiddenError,
    SurveyConflictError,
    SurveyValidationError,
    SubmissionValidationError,
)


@router.get(
    "/{slug}",
    response_model=PublicSurveyOut,
    summary="按 Slug 获取公开问卷信息",
)
async def get_public_survey(
    service: PublicServiceDep,
    slug: str = Path(..., pattern=SLUG_PATTERN),
) -> PublicSurveyOut:
    try:
        return await service.get_by_slug(slug)
    except _DOMAIN_ERRORS as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{slug}/next",
    response_model=AdvanceOut,
    summary="计算下一道应展示的题目（服务端跳转）",
)
async def advance_public_survey(
    user_id: OptionalCurrentUserIdDep,
    service: PublicServiceDep,
    payload: AdvanceIn,
    slug: str = Path(..., pattern=SLUG_PATTERN),
) -> AdvanceOut:
    try:
        return await service.advance(slug, payload, user_id)
    except _DOMAIN_ERRORS as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{slug}/responses",
    response_model=SubmitOut,
    status_code=status.HTTP_201_CREATED,
    summary="通过公开链接提交答卷",
)
async def submit_public_survey(
    user_id: OptionalCurrentUserIdDep,
    service: PublicServiceDep,
    payload: SubmitIn,
    slug: str = Path(..., pattern=SLUG_PATTERN),
) -> SubmitOut:
    try:
        return await service.submit(slug, payload, user_id)
    except _DOMAIN_ERRORS as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


__all__ = ["router"]
