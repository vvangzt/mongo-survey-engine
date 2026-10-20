"""Map survey-domain exceptions to HTTP responses."""

from __future__ import annotations

from fastapi import HTTPException, status

from schemas.pydantic import SubmissionValidationError

from .service import (
    SurveyConflictError,
    SurveyForbiddenError,
    SurveyNotFoundError,
    SurveyUnauthenticatedError,
    SurveyValidationError,
)


def raise_http_error(exc: Exception) -> None:
    if isinstance(exc, SurveyNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if isinstance(exc, SurveyUnauthenticatedError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if isinstance(exc, SurveyForbiddenError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    if isinstance(exc, SurveyConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if isinstance(exc, SurveyValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, SubmissionValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": exc.code or "submission_invalid",
                "message": str(exc),
                "question_id": exc.question_id,
            },
        ) from exc
    raise exc


__all__ = ["raise_http_error"]
