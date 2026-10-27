"""Question bank (题库) HTTP endpoints: requirement 7."""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Path, status

from ..dependencies import CurrentUserIdDep, QuestionServiceDep
from .http_errors import raise_http_error
from .schemas import (
    LibraryCreateIn,
    LibraryDetailOut,
    LibraryItemIn,
    LibraryItemOut,
    LibraryOut,
    LibraryUpdateIn,
)
from .service import (
    QuestionConflictError,
    QuestionNotFoundError,
    QuestionValidationError,
)

router = APIRouter(prefix="/api/libraries", tags=["question-libraries"])

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


def _object_id(raw: str, message: str = "library not found") -> ObjectId:
    try:
        return ObjectId(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=message
        ) from exc


@router.post(
    "",
    response_model=LibraryOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建题库",
)
async def create_library(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: LibraryCreateIn,
) -> LibraryOut:
    return await _run(service.create_library(user_id, payload))


@router.get(
    "",
    response_model=list[LibraryOut],
    summary="我的题库（可选包含公开题库）",
)
async def list_libraries(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    include_public: bool = True,
) -> list[LibraryOut]:
    return await _run(
        service.list_libraries(user_id, include_public=include_public)
    )


@router.get(
    "/{library_id}",
    response_model=LibraryDetailOut,
    summary="题库详情与条目",
)
async def get_library(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    library_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> LibraryDetailOut:
    return await _run(service.get_library(user_id, _object_id(library_id)))


@router.patch(
    "/{library_id}",
    response_model=LibraryOut,
    summary="修改题库名称、说明或可见性",
)
async def update_library(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: LibraryUpdateIn,
    library_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> LibraryOut:
    return await _run(
        service.update_library(
            user_id, _object_id(library_id), payload
        )
    )


@router.delete(
    "/{library_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除题库（题目本身不受影响）",
)
async def delete_library(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    library_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> None:
    await _run(service.delete_library(user_id, _object_id(library_id)))


@router.post(
    "/{library_id}/items",
    response_model=LibraryItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="把题目加入题库（重复加入幂等）",
)
async def add_library_item(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    payload: LibraryItemIn,
    library_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> LibraryItemOut:
    return await _run(
        service.add_library_item(
            user_id, _object_id(library_id), payload
        )
    )


@router.delete(
    "/{library_id}/items/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="把题目移出题库",
)
async def remove_library_item(
    user_id: CurrentUserIdDep,
    service: QuestionServiceDep,
    library_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
    entity_id: str = Path(..., pattern=OBJECT_ID_PATTERN),
) -> None:
    await _run(
        service.remove_library_item(
            user_id,
            _object_id(library_id),
            _object_id(entity_id, "library item not found"),
        )
    )


__all__ = ["router"]
