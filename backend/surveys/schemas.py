"""API request/response models for the minimal survey authoring API.

Question and answer payloads reuse the canonical Pydantic domain models, so
authoring, publishing and submission all enforce the same rules.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.pydantic.models import (
    Answer,
    JumpLogic,
    ObjectIdStr,
    Question,
    QuestionId,
    Slug,
    SubmissionToken,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SurveyCreateIn(StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    allow_anonymous: bool = False
    allow_multiple_responses: bool = True
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    slug: Slug | None = None

    @model_validator(mode="after")
    def check_window(self) -> "SurveyCreateIn":
        if (
            self.opens_at is not None
            and self.closes_at is not None
            and self.opens_at >= self.closes_at
        ):
            raise ValueError("opens_at must be earlier than closes_at")
        return self


class SurveyCreatedOut(BaseModel):
    id: str
    slug: str
    title: str
    status: str
    allow_anonymous: bool
    allow_multiple_responses: bool
    current_draft_version_id: str
    created_at: datetime


class SurveyUpdateIn(StrictRequest):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    allow_anonymous: bool | None = None
    allow_multiple_responses: bool | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None

    @model_validator(mode="after")
    def check_window(self) -> "SurveyUpdateIn":
        if (
            self.opens_at is not None
            and self.closes_at is not None
            and self.opens_at >= self.closes_at
        ):
            raise ValueError("opens_at must be earlier than closes_at")
        return self


class VersionOut(BaseModel):
    id: str
    version_no: int
    state: str
    revision: int
    questions: list[Question]


class DraftUpdateIn(StrictRequest):
    revision: int = Field(ge=1)
    questions: list[Question] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def unique_question_ids(self) -> "DraftUpdateIn":
        question_ids = [question.question_id for question in self.questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question_id values must be unique")
        return self


class SurveyListItem(BaseModel):
    id: str
    slug: str
    title: str
    description: str = ""
    status: str
    allow_anonymous: bool
    allow_multiple_responses: bool
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SurveyDetailOut(SurveyListItem):
    current_draft: VersionOut | None = None
    published_version: VersionOut | None = None


class ClosedOut(BaseModel):
    id: str
    status: str
    closed_at: datetime


class QuestionAddedOut(BaseModel):
    survey_id: str
    survey_version_id: str
    revision: int
    question: Question


class PublishedOut(BaseModel):
    survey_id: str
    survey_version_id: str
    version_no: int
    slug: str
    status: str
    published_at: datetime


class FromLibraryIn(StrictRequest):
    """Insert a shared-library question into the survey draft."""

    question_version_id: ObjectIdStr
    question_id: QuestionId | None = None
    logic: JumpLogic | None = None


class SubmitIn(StrictRequest):
    answers: list[Answer] = Field(default_factory=list, max_length=300)
    is_anonymous: bool = False
    submission_token: SubmissionToken

    @model_validator(mode="after")
    def unique_answers(self) -> "SubmitIn":
        question_ids = [answer.question_id for answer in self.answers]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("a response may answer each question only once")
        return self


class SubmitOut(BaseModel):
    response_id: str
    survey_id: str
    survey_version_id: str
    is_anonymous: bool
    submitted_at: datetime
    question_path: list[str]


__all__ = [
    "ClosedOut",
    "DraftUpdateIn",
    "FromLibraryIn",
    "PublishedOut",
    "QuestionAddedOut",
    "SubmitIn",
    "SubmitOut",
    "SurveyCreateIn",
    "SurveyCreatedOut",
    "SurveyDetailOut",
    "SurveyListItem",
    "SurveyUpdateIn",
    "VersionOut",
]
