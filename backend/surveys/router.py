"""HTTP endpoints needed by the end-to-end system tests."""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Path, status

from schemas.pydantic import Question, SubmissionValidationError

from ..dependencies import (
    CurrentUserIdDep,
    OptionalCurrentUserIdDep,
    SurveyServiceDep,
)
from .schemas import (
    ClosedOut,
    DraftUpdateIn,
    PublishedOut,
    QuestionAddedOut,
    SubmitIn,
    SubmitOut,
    SurveyCreateIn,
    SurveyCreatedOut,
    SurveyDetailOut,
    SurveyListItem,
    SurveyUpdateIn,
    VersionOut,
)
from .http_errors import raise_http_error
from .service import (
    SurveyConflictError,
    SurveyForbiddenError,
    SurveyNotFoundError,
    SurveyUnauthenticatedError,
    SurveyValidationError,
)

router = APIRouter(prefix="/api/surveys", tags=["surveys"])
SURVEY_ID_PATTERN = r"^[0-9a-fA-F]{24}$"


def _object_id(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="survey not found",
        ) from exc


@router.post(
    "",
    response_model=SurveyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建问卷草稿",
)
async def create_survey(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    payload: SurveyCreateIn,
) -> SurveyCreatedOut:
    try:
        return await service.create_survey(user_id, payload)
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "",
    response_model=list[SurveyListItem],
    summary="查看当前用户创建的问卷列表",
)
async def list_surveys(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
) -> list[SurveyListItem]:
    try:
        return await service.list_surveys(user_id)
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/{survey_id}",
    response_model=SurveyDetailOut,
    summary="查看本人的问卷详情与版本",
)
async def get_survey(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> SurveyDetailOut:
    try:
        return await service.get_survey(user_id, _object_id(survey_id))
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.patch(
    "/{survey_id}",
    response_model=SurveyDetailOut,
    summary="修改问卷元数据、匿名策略和截止时间",
)
async def update_survey(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    payload: SurveyUpdateIn,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> SurveyDetailOut:
    try:
        return await service.update_survey(
            user_id, _object_id(survey_id), payload
        )
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{survey_id}/close",
    response_model=ClosedOut,
    summary="关闭问卷",
)
async def close_survey(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> ClosedOut:
    try:
        return await service.close_survey(user_id, _object_id(survey_id))
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{survey_id}/questions",
    response_model=QuestionAddedOut,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="向草稿问卷添加题目",
)
async def add_question(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    question: Question,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> QuestionAddedOut:
    try:
        return await service.add_question(
            user_id, _object_id(survey_id), question
        )
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{survey_id}/new-draft",
    response_model=VersionOut,
    summary="从已发布版本创建新草稿版本",
)
async def create_new_draft(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> VersionOut:
    try:
        return await service.create_new_draft(
            user_id, _object_id(survey_id)
        )
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.put(
    "/{survey_id}/draft",
    response_model=VersionOut,
    summary="保存整份草稿题目（编辑器使用）",
)
async def replace_draft(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    payload: DraftUpdateIn,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> VersionOut:
    try:
        return await service.replace_draft(
            user_id, _object_id(survey_id), payload
        )
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{survey_id}/publish",
    response_model=PublishedOut,
    summary="发布问卷并冻结版本",
)
async def publish_survey(
    user_id: CurrentUserIdDep,
    service: SurveyServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> PublishedOut:
    try:
        return await service.publish_survey(user_id, _object_id(survey_id))
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/{survey_id}/responses",
    response_model=SubmitOut,
    status_code=status.HTTP_201_CREATED,
    summary="提交答卷（支持匿名）",
)
async def submit_response(
    user_id: OptionalCurrentUserIdDep,
    service: SurveyServiceDep,
    payload: SubmitIn,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> SubmitOut:
    try:
        return await service.submit_response(
            _object_id(survey_id), payload, user_id
        )
    except (
        SurveyNotFoundError,
        SurveyUnauthenticatedError,
        SurveyForbiddenError,
        SurveyConflictError,
        SurveyValidationError,
        SubmissionValidationError,
    ) as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")


__all__ = ["router"]
