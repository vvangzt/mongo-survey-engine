"""Pydantic response models for the statistics API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

QuestionType = Literal["single_choice", "multi_choice", "text", "number"]


class SurveySummary(BaseModel):
    id: str
    title: str
    status: str


class VersionSummary(BaseModel):
    id: str
    version_no: int
    published_at: datetime | None = None


class OptionStat(BaseModel):
    option_id: str
    label: str
    count: int = Field(ge=0)
    percentage: float = Field(
        ge=0,
        le=100,
        description=(
            "Percentage of respondents who answered this question and selected "
            "the option. Multi-choice percentages may sum to more than 100."
        ),
    )


class QuestionOverview(BaseModel):
    question_id: str
    type: QuestionType
    title: str
    required: bool
    answered_count: int = Field(ge=0)
    response_rate: float = Field(
        ge=0,
        le=1,
        description="answered_count divided by all submissions in the version.",
    )
    option_counts: list[OptionStat] | None = None
    average: float | None = None
    min: int | float | None = None
    max: int | float | None = None


class SurveyStatsOverview(BaseModel):
    survey: SurveySummary
    version: VersionSummary
    response_count: int = Field(ge=0)
    questions: list[QuestionOverview]
    generated_at: datetime


class TextAnswerItem(BaseModel):
    text: str
    submitted_at: datetime | None = None


class Pagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class QuestionStatsDetail(BaseModel):
    survey_id: str
    survey_version_id: str
    question_id: str
    type: QuestionType
    title: str
    required: bool
    answered_count: int = Field(ge=0)

    option_counts: list[OptionStat] | None = None
    average: float | None = None
    min: int | float | None = None
    max: int | float | None = None

    answers: list[TextAnswerItem] | None = None
    pagination: Pagination | None = None

    generated_at: datetime


__all__ = [
    "OptionStat",
    "Pagination",
    "QuestionOverview",
    "QuestionStatsDetail",
    "QuestionType",
    "SurveyStatsOverview",
    "SurveySummary",
    "TextAnswerItem",
    "VersionSummary",
]
