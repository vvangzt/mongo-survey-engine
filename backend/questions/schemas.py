"""Request/response models for the shared question library API.

The naming convention matters here (see ``docs/api.md``):

* ``question_id`` inside a survey is the **instance** id (``q_xxx`` string);
* ``entity_id`` is the **library** identity (ObjectId) and is what
  ``/api/questions/{id}`` takes;
* ``version_id`` is one immutable content version of that entity.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from schemas.pydantic import (
    LibraryVisibility,
    QuestionContent,
    QuestionVisibility,
    SharePermission,
)
from schemas.pydantic.models import ObjectIdStr, Username


class StrictRequest(BaseModel):
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------


class QuestionCreateIn(StrictRequest):
    content: QuestionContent
    visibility: QuestionVisibility = QuestionVisibility.private


class QuestionVersionIn(StrictRequest):
    """Create a new immutable version of an existing question."""

    content: QuestionContent


class QuestionForkIn(StrictRequest):
    """Derive a brand-new question from an existing one."""

    content: QuestionContent | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)


class ShareGrantIn(StrictRequest):
    grantee_username: Username
    permission: SharePermission = SharePermission.use


class ShareOut(BaseModel):
    entity_id: str
    grantee_id: str
    grantee_username: str
    permission: SharePermission
    created_at: datetime


class QuestionVersionOut(BaseModel):
    id: str
    entity_id: str
    version_no: int
    parent_version_id: str | None = None
    restored_from_version_id: str | None = None
    content: QuestionContent
    content_hash: str
    created_at: datetime


class QuestionSummary(BaseModel):
    id: str
    owner_id: str
    owner_username: str | None = None
    type: str
    title: str
    visibility: QuestionVisibility
    latest_version_no: int
    version_count: int
    created_at: datetime
    updated_at: datetime
    is_owner: bool = False
    can_edit: bool = False


class QuestionDetailOut(QuestionSummary):
    latest_version: QuestionVersionOut
    versions: list[QuestionVersionOut] = Field(default_factory=list)
    shares: list[ShareOut] = Field(default_factory=list)
    usage_count: int = 0


class QuestionUsageOut(BaseModel):
    survey_id: str
    survey_title: str
    survey_status: str
    survey_version_id: str
    survey_version_no: int
    instance_question_id: str
    question_version_id: str
    question_version_no: int
    is_published: bool


# ---------------------------------------------------------------------------
# question banks
# ---------------------------------------------------------------------------


class LibraryCreateIn(StrictRequest):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    visibility: LibraryVisibility = LibraryVisibility.private


class LibraryUpdateIn(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    visibility: LibraryVisibility | None = None


class LibraryItemIn(StrictRequest):
    entity_id: ObjectIdStr
    note: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def check_tags(self) -> "LibraryItemIn":
        for tag in self.tags:
            if not tag or len(tag) > 32:
                raise ValueError("each tag must be 1..32 characters")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must not contain duplicates")
        return self


class LibraryItemOut(BaseModel):
    entity_id: str
    title: str
    type: str
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    latest_version_id: str
    latest_version_no: int
    added_at: datetime


class LibraryOut(BaseModel):
    id: str
    owner_id: str
    owner_username: str | None = None
    name: str
    description: str = ""
    visibility: LibraryVisibility
    item_count: int = 0
    created_at: datetime
    updated_at: datetime
    is_owner: bool = False


class LibraryDetailOut(LibraryOut):
    items: list[LibraryItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# cross-survey statistics
# ---------------------------------------------------------------------------


class CrossOptionCount(BaseModel):
    option_id: str
    label: str
    count: int
    versions: list[int] = Field(default_factory=list)


class CrossVersionBreakdown(BaseModel):
    version_id: str
    version_no: int
    answered_count: int


class CrossQuestionStatsOut(BaseModel):
    entity_id: str
    question_id: str | None = None
    type: str
    title: str
    answered_count: int
    survey_count: int
    version_count: int
    versions: list[CrossVersionBreakdown] = Field(default_factory=list)
    option_counts: list[CrossOptionCount] = Field(default_factory=list)
    option_set_mismatch: bool = False
    merged_by: str = "option_id"
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    numeric_count: int = 0
    text_count: int = 0
    generated_at: datetime


class CrossTextAnswer(BaseModel):
    text: str
    survey_id: str
    survey_title: str
    version_no: int
    submitted_at: datetime


class CrossTextPageOut(BaseModel):
    entity_id: str
    question_version_no: int | None = None
    total: int
    page: int
    page_size: int
    total_pages: int
    answers: list[CrossTextAnswer] = Field(default_factory=list)
    generated_at: datetime


__all__ = [
    "CrossOptionCount",
    "CrossQuestionStatsOut",
    "CrossTextAnswer",
    "CrossTextPageOut",
    "CrossVersionBreakdown",
    "LibraryCreateIn",
    "LibraryDetailOut",
    "LibraryItemIn",
    "LibraryItemOut",
    "LibraryOut",
    "LibraryUpdateIn",
    "QuestionCreateIn",
    "QuestionDetailOut",
    "QuestionForkIn",
    "QuestionSummary",
    "QuestionUsageOut",
    "QuestionVersionIn",
    "QuestionVersionOut",
    "ShareGrantIn",
    "ShareOut",
]
