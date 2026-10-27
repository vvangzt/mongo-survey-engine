"""Map question-library exceptions to HTTP responses.

The shape matches the survey API: a plain ``detail`` string for ordinary
errors and a ``{code, message, ...}`` object for domain validation failures.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from .service import (
    QuestionConflictError,
    QuestionNotFoundError,
    QuestionValidationError,
)


def raise_http_error(exc: Exception) -> None:
    if isinstance(exc, QuestionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if isinstance(exc, QuestionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if isinstance(exc, QuestionValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "question_invalid", "message": str(exc)},
        ) from exc
    raise exc


__all__ = ["raise_http_error"]
