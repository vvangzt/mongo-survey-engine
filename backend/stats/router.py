"""FastAPI routes for survey statistics."""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Path, Query, status

from ..dependencies import CurrentUserIdDep, StatsServiceDep
from .schemas import QuestionStatsDetail, SurveyStatsOverview
from .service import StatsNotFoundError, StatsUnavailableError

router = APIRouter(prefix="/api/surveys", tags=["survey-stats"])

SURVEY_ID_PATTERN = r"^[0-9a-fA-F]{24}$"
QUESTION_ID_PATTERN = r"^q_[A-Za-z0-9_-]{8,64}$"


def _object_id(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="survey not found",
        ) from exc


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=message,
    )


def _conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=message,
    )


@router.get(
    "/{survey_id}/stats",
    response_model=SurveyStatsOverview,
    response_model_exclude_none=True,
    summary="获取整份问卷的统计总览",
    description=(
        "统计当前已发布版本的整份问卷。返回每个选项的人数、数字题均值/最值、"
        "文本题作答数量；文本内容通过单题统计接口分页读取。"
    ),
)
async def get_survey_stats(
    user_id: CurrentUserIdDep,
    service: StatsServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
) -> SurveyStatsOverview:
    try:
        return await service.get_overview(_object_id(survey_id), user_id)
    except StatsNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except StatsUnavailableError as exc:
        raise _conflict(str(exc)) from exc


@router.get(
    "/{survey_id}/questions/{qid}/stats",
    response_model=QuestionStatsDetail,
    response_model_exclude_none=True,
    summary="获取单道题目的详细统计",
    description=(
        "按题目类型返回选项频次、数字统计或分页文本答案。"
        "page/page_size 仅对文本题生效，page_size 最大 100。"
    ),
)
async def get_question_stats(
    user_id: CurrentUserIdDep,
    service: StatsServiceDep,
    survey_id: str = Path(..., pattern=SURVEY_ID_PATTERN),
    qid: str = Path(..., pattern=QUESTION_ID_PATTERN),
    page: int = Query(1, ge=1, description="文本题页码，从 1 开始"),
    page_size: int = Query(
        20, ge=1, le=100, description="文本题每页数量，最大 100"
    ),
) -> QuestionStatsDetail:
    try:
        return await service.get_question_stats(
            _object_id(survey_id),
            user_id,
            qid,
            page=page,
            page_size=page_size,
        )
    except StatsNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except StatsUnavailableError as exc:
        raise _conflict(str(exc)) from exc


__all__ = ["router"]
