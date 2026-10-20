"""Request/response models for public survey filling."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schemas.pydantic.models import Answer, QuestionId


class PublicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicQuestion(BaseModel):
    question_id: str
    type: str
    title: str
    description: str | None = None
    required: bool
    options: list[dict[str, Any]] | None = None
    validation: dict[str, Any] | None = None


class PublicSurveyOut(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    status: str
    allow_anonymous: bool
    allow_multiple_responses: bool
    requires_login: bool
    is_open: bool
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    version_no: int


class AdvanceIn(PublicRequest):
    answers: list[Answer] = Field(default_factory=list, max_length=300)
    skipped_question_ids: list[QuestionId] = Field(
        default_factory=list, max_length=300
    )


class AdvanceOut(BaseModel):
    survey_id: str
    survey_version_id: str
    next_question: PublicQuestion | None = None
    completed: bool
    path: list[str]
    version_no: int


__all__ = [
    "AdvanceIn",
    "AdvanceOut",
    "PublicQuestion",
    "PublicSurveyOut",
]
