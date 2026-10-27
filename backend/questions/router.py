"""Question-library HTTP endpoints (phase 2, requirements 1-6 and 8)."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Path, Query, status

from ..dependencies import (
    CrossSurveyStatsDep,
    CurrentUserIdDep,
    QuestionServiceDep,
)
from .http_errors import raise_http_error
from .schemas import (
    CrossQuestionStatsOut,
    CrossTextPageOut,
    QuestionCreateIn,
    QuestionDetailOut,
    QuestionForkIn,
    QuestionSummary,
    QuestionUsageOut,
    QuestionVersionIn,
    QuestionVersionOut,
    ShareGrantIn,
    ShareOut,
)
from .service import (
    QuestionConflictError,
    QuestionNotFoundError,
    QuestionValidationError,
)

router = APIRouter(prefix="/api/questions", tags=["questions"])

OBJECT_ID_PATTERN = r"^[0-9a-fA-F]{24}$"

_DOMAIN_ERRORS = (
    QuestionNotFoundError,
    QuestionConflictError,
    QuestionValidationError,
)


async def _run(awaitable: Any) -> Any:
    try:
        return await awaitable
    except _DOMAIN_ERRORS as exc:
        raise_http_error(exc)
        raise AssertionError("unreachable")  # pragma: no cover


def _object_id(raw: str, message: str = "question not found") -> ObjectId:
    try:
        return ObjectId(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=message
        ) from exc


@router.post(
    "",
    response_model=QuestionDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建题目（同时生成 v1 版本）",
)
async def create_question(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: QuestionCreateIn,
) -> QuestionDetailOut:
    return await _run(service.create_question(user_id, payload))


@router.get(
    "",
    response_model=list[QuestionSummary],
    summary="题目列表（mine / shared / public / usable / library）",
)
async def list_questions(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    scope: str = Query(default="usable", pattern="^(mine|shared|public|usable|library)$"),
    type: str | None = Query(default=None, pattern="^(single_choice|multi_choice|text|number)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=200),
) -> list[QuestionSummary]:
    return await _run(
        service.list_questions(
            user_id, scope=scope, type_filter=type, text=q, limit=limit
        )
    )


@router.get(
    "/{question_id}",
    response_model=QuestionDetailOut,
    summary="题目详情：最新版本 + 版本历史 + 共享 + 使用次数",
)
async def get_question(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> QuestionDetailOut:
    return await _run(service.get_question(user_id, _object_id(question_id)))


@router.post(
    "/{question_id}/versions",
    response_model=QuestionVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="改题：生成新的不可变版本（旧问卷不受影响）",
)
async def create_version(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: QuestionVersionIn,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> QuestionVersionOut:
    return await _run(
        service.create_version(
            user_id, _object_id(question_id), payload
        )
    )


@router.get(
    "/{question_id}/versions",
    response_model=list[QuestionVersionOut],
    summary="版本历史（v1 → v2 → v3）",
)
async def list_versions(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> list[QuestionVersionOut]:
    return await _run(service.list_versions(user_id, _object_id(question_id)))


@router.post(
    "/{question_id}/versions/{version_no}/restore",
    response_model=QuestionVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="恢复旧版本（以旧内容生成新版本）",
)
async def restore_version(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
    version_no: int = Path(..., ge=1),
) -> QuestionVersionOut:
    return await _run(
        service.restore_version(
            user_id, _object_id(question_id), version_no
        )
    )


@router.post(
    "/{question_id}/fork",
    response_model=QuestionDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="基于现有题目派生一个新题目（记录来源）",
)
async def fork_question(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: QuestionForkIn,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> QuestionDetailOut:
    return await _run(
        service.fork_question(user_id, _object_id(question_id), payload)
    )


@router.get(
    "/{question_id}/usages",
    response_model=list[QuestionUsageOut],
    summary="这道题被哪些问卷（及哪个版本）使用",
)
async def list_usages(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> list[QuestionUsageOut]:
    return await _run(service.list_usages(user_id, _object_id(question_id)))


@router.post(
    "/{question_id}/shares",
    response_model=ShareOut,
    status_code=status.HTTP_201_CREATED,
    summary="把题目共享给另一个用户",
)
async def share_question(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: ShareGrantIn,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> ShareOut:
    return await _run(
        service.share_question(user_id, _object_id(question_id), payload)
    )


@router.get(
    "/{question_id}/shares",
    response_model=list[ShareOut],
    summary="查看共享名单",
)
async def list_shares(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> list[ShareOut]:
    return await _run(service.list_shares(user_id, _object_id(question_id)))


@router.delete(
    "/{question_id}/shares/{grantee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="撤销共享",
)
async def revoke_share(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
    grantee_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> None:
    await _run(
        service.revoke_share(
            user_id, _object_id(question_id), _object_id(grantee_id, "share not found")
        )
    )


@router.delete(
    "/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删除题目（被已发布问卷引用时拒绝）",
)
async def delete_question(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> None:
    await _run(service.delete_question(user_id, _object_id(question_id)))


@router.get(
    "/{question_id}/stats",
    response_model=CrossQuestionStatsOut,
    summary="跨问卷统计：这道题在所有问卷里的回答情况",
)
async def question_stats(
    user_id: CurrentUserIdDep,
    stats: CrossSurveyStatsDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
    version: str = Query(default="all", pattern="^(all|latest|[0-9]+)$"),
    survey_id: str | None = Query(default=None, pattern=OBJECT_ID_PATTERN),
) -> CrossQuestionStatsOut:
    return await _run(
        stats.overview(
            user_id,
            _object_id(question_id),
            version=version,
            survey_id=ObjectId(survey_id) if survey_id else None,
        )
    )


@router.get(
    "/{question_id}/stats/answers",
    response_model=CrossTextPageOut,
    summary="跨问卷统计：文本题的全部回答（分页）",
)
async def question_text_answers(
    user_id: CurrentUserIdDep,
    stats: CrossSurveyStatsDep,
    question_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
    version: str = Query(default="all", pattern="^(all|latest|[0-9]+)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    survey_id: str | None = Query(default=None, pattern=OBJECT_ID_PATTERN),
) -> CrossTextPageOut:
    return await _run(
        stats.text_page(
            user_id,
            _object_id(question_id),
            version=version,
            page=page,
            page_size=page_size,
            survey_id=ObjectId(survey_id) if survey_id else None,
        )
    )


__all__ = ["router"]
