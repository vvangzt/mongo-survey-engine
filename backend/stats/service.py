"""Statistics use-cases and result post-processing.

The service is deliberately separated from FastAPI: all aggregation and mapping
can be tested without an HTTP server. MongoDB returns grouped rows; option
labels, zero-count options, percentages and pagination metadata are assembled
from the immutable survey version so charts have a stable shape.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from .pipelines import (
    build_choice_question_pipeline,
    build_number_question_pipeline,
    build_overview_pipeline,
    build_text_question_pipeline,
)
from .schemas import (
    OptionStat,
    Pagination,
    QuestionOverview,
    QuestionStatsDetail,
    SurveyStatsOverview,
    SurveySummary,
    TextAnswerItem,
    VersionSummary,
)


class StatsNotFoundError(Exception):
    """Survey/question does not exist or is not owned by the caller."""


class StatsUnavailableError(Exception):
    """The survey has no usable published version or contains invalid data."""


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise StatsUnavailableError("expected a datetime in survey metadata")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_value(rows: list[dict[str, Any]] | None) -> int:
    if not rows:
        return 0
    return int(rows[0].get("value", 0))


def _option_stats(
    question: dict[str, Any],
    counts: dict[tuple[str, str], int],
    answered_count: int,
) -> list[OptionStat]:
    qid = question["question_id"]
    result: list[OptionStat] = []
    for option in question.get("options", []):
        option_id = option["option_id"]
        count = counts.get((qid, option_id), 0)
        percentage = (
            round(count / answered_count * 100, 2) if answered_count > 0 else 0.0
        )
        result.append(
            OptionStat(
                option_id=option_id,
                label=option.get("label", option_id),
                count=count,
                percentage=percentage,
            )
        )
    return result


def build_overview_response(
    survey: dict[str, Any],
    version: dict[str, Any],
    raw: dict[str, Any],
    *,
    generated_at: datetime,
) -> SurveyStatsOverview:
    """Map one overview aggregation document to the public response model."""

    response_count = _first_value(raw.get("response_count"))
    answered_by_question = {
        row["_id"]: int(row.get("answered_count", 0))
        for row in raw.get("choice_answered", [])
        if row.get("_id") is not None
    }

    option_counts: dict[tuple[str, str], int] = {}
    for row in raw.get("choice_options", []):
        group_id = row.get("_id") or {}
        qid = group_id.get("question_id")
        option_id = group_id.get("option_id")
        if qid is not None and option_id is not None:
            option_counts[(qid, option_id)] = int(row.get("count", 0))

    number_stats = {
        row["_id"]: row
        for row in raw.get("number_stats", [])
        if row.get("_id") is not None
    }
    text_stats = {
        row["_id"]: int(row.get("answered_count", 0))
        for row in raw.get("text_stats", [])
        if row.get("_id") is not None
    }

    questions: list[QuestionOverview] = []
    for question in version.get("questions", []):
        qid = question["question_id"]
        qtype = question["type"]
        title = question.get("title", "")
        required = bool(question.get("required", False))

        if qtype in ("single_choice", "multi_choice"):
            answered_count = answered_by_question.get(qid, 0)
            questions.append(
                QuestionOverview(
                    question_id=qid,
                    type=qtype,
                    title=title,
                    required=required,
                    answered_count=answered_count,
                    response_rate=(
                        round(answered_count / response_count, 4)
                        if response_count
                        else 0.0
                    ),
                    option_counts=_option_stats(
                        question, option_counts, answered_count
                    ),
                )
            )
            continue

        if qtype == "number":
            row = number_stats.get(qid)
            answered_count = (
                int(row.get("answered_count", 0)) if row else 0
            )
            average = (
                round(float(row["average"]), 4)
                if row and row.get("average") is not None
                else None
            )
            questions.append(
                QuestionOverview(
                    question_id=qid,
                    type=qtype,
                    title=title,
                    required=required,
                    answered_count=answered_count,
                    response_rate=(
                        round(answered_count / response_count, 4)
                        if response_count
                        else 0.0
                    ),
                    average=average,
                    min=row.get("minimum") if row else None,
                    max=row.get("maximum") if row else None,
                )
            )
            continue

        if qtype == "text":
            answered_count = text_stats.get(qid, 0)
            questions.append(
                QuestionOverview(
                    question_id=qid,
                    type=qtype,
                    title=title,
                    required=required,
                    answered_count=answered_count,
                    response_rate=(
                        round(answered_count / response_count, 4)
                        if response_count
                        else 0.0
                    ),
                )
            )
            continue

        raise StatsUnavailableError(
            f"unsupported question type in version: {qtype!r}"
        )

    return SurveyStatsOverview(
        survey=SurveySummary(
            id=str(survey["_id"]),
            title=survey.get("title", ""),
            status=survey.get("status", ""),
        ),
        version=VersionSummary(
            id=str(version["_id"]),
            version_no=int(version.get("version_no", 0)),
            published_at=_utc(version.get("published_at")),
        ),
        response_count=response_count,
        questions=questions,
        generated_at=generated_at,
    )


def _common_detail(
    *,
    survey_id: ObjectId,
    version_id: ObjectId,
    question: dict[str, Any],
    answered_count: int,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "survey_id": str(survey_id),
        "survey_version_id": str(version_id),
        "question_id": question["question_id"],
        "type": question["type"],
        "title": question.get("title", ""),
        "required": bool(question.get("required", False)),
        "answered_count": answered_count,
        "generated_at": generated_at,
    }


def build_choice_detail_response(
    *,
    survey_id: ObjectId,
    version_id: ObjectId,
    question: dict[str, Any],
    raw: dict[str, Any],
    generated_at: datetime,
) -> QuestionStatsDetail:
    answered_count = _first_value(raw.get("answered"))
    counts = {
        row["_id"]: int(row.get("count", 0))
        for row in raw.get("options", [])
        if row.get("_id") is not None
    }
    return QuestionStatsDetail(
        **_common_detail(
            survey_id=survey_id,
            version_id=version_id,
            question=question,
            answered_count=answered_count,
            generated_at=generated_at,
        ),
        option_counts=_option_stats(question, {(question["question_id"], k): v for k, v in counts.items()}, answered_count),
    )


def build_number_detail_response(
    *,
    survey_id: ObjectId,
    version_id: ObjectId,
    question: dict[str, Any],
    raw: dict[str, Any],
    generated_at: datetime,
) -> QuestionStatsDetail:
    rows = raw.get("stats") or []
    stats = rows[0] if rows else {}
    answered_count = int(stats.get("answered_count", 0))
    average = (
        round(float(stats["average"]), 4)
        if stats.get("average") is not None
        else None
    )
    return QuestionStatsDetail(
        **_common_detail(
            survey_id=survey_id,
            version_id=version_id,
            question=question,
            answered_count=answered_count,
            generated_at=generated_at,
        ),
        average=average,
        min=stats.get("minimum") if stats else None,
        max=stats.get("maximum") if stats else None,
    )


def build_text_detail_response(
    *,
    survey_id: ObjectId,
    version_id: ObjectId,
    question: dict[str, Any],
    raw: dict[str, Any],
    page: int,
    page_size: int,
    generated_at: datetime,
) -> QuestionStatsDetail:
    total = _first_value(raw.get("meta"))
    answers = [
        TextAnswerItem(
            text=row.get("text", ""),
            submitted_at=_utc(row.get("submitted_at")),
        )
        for row in raw.get("page", [])
    ]
    return QuestionStatsDetail(
        **_common_detail(
            survey_id=survey_id,
            version_id=version_id,
            question=question,
            answered_count=total,
            generated_at=generated_at,
        ),
        answers=answers,
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        ),
    )


class StatsService:
    """Read-only statistics service scoped to a survey owner and version."""

    def __init__(
        self,
        db: AsyncDatabase,
        *,
        max_time_ms: int = 30_000,
    ) -> None:
        self._surveys = db["surveys"]
        self._versions = db["survey_versions"]
        self._responses = db["responses"]
        self._max_time_ms = max_time_ms

    async def _aggregate(
        self, pipeline: list[dict[str, Any]], *, comment: str
    ) -> dict[str, Any]:
        cursor = await self._responses.aggregate(
            pipeline,
            allowDiskUse=True,
            maxTimeMS=self._max_time_ms,
            comment=comment,
        )
        try:
            rows = await cursor.to_list(length=1)
        finally:
            await cursor.close()
        return rows[0] if rows else {}

    async def _load_context(
        self, survey_id: ObjectId, owner_id: ObjectId
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            },
            {
                "_id": 1,
                "title": 1,
                "status": 1,
                "published_version_id": 1,
            },
        )
        if survey is None:
            # Deliberately 404 for both "missing" and "not owned": do not leak
            # the existence of another user's survey.
            raise StatsNotFoundError("survey not found")

        version_id = survey.get("published_version_id")
        if version_id is None:
            raise StatsUnavailableError(
                "survey has no published version; statistics are unavailable"
            )

        version = await self._versions.find_one(
            {
                "_id": version_id,
                "survey_id": survey_id,
                "state": "published",
            },
            {
                "_id": 1,
                "version_no": 1,
                "published_at": 1,
                "questions": 1,
            },
        )
        if version is None:
            raise StatsUnavailableError(
                "published survey version is missing or unavailable"
            )
        if not version.get("questions"):
            raise StatsUnavailableError("published version has no questions")
        return survey, version

    async def get_overview(
        self, survey_id: ObjectId, owner_id: ObjectId
    ) -> SurveyStatsOverview:
        survey, version = await self._load_context(survey_id, owner_id)
        raw = await self._aggregate(
            build_overview_pipeline(survey_id, version["_id"]),
            comment="survey_stats_overview",
        )
        return build_overview_response(
            survey,
            version,
            raw,
            generated_at=datetime.now(timezone.utc),
        )

    async def get_question_stats(
        self,
        survey_id: ObjectId,
        owner_id: ObjectId,
        qid: str,
        *,
        page: int,
        page_size: int,
    ) -> QuestionStatsDetail:
        survey, version = await self._load_context(survey_id, owner_id)
        question = next(
            (
                item
                for item in version["questions"]
                if item.get("question_id") == qid
            ),
            None,
        )
        if question is None:
            raise StatsNotFoundError("question not found in published version")

        qtype = question.get("type")
        generated_at = datetime.now(timezone.utc)

        if qtype in ("single_choice", "multi_choice"):
            raw = await self._aggregate(
                build_choice_question_pipeline(
                    survey_id, version["_id"], qid, qtype
                ),
                comment="survey_stats_question_choice",
            )
            return build_choice_detail_response(
                survey_id=survey_id,
                version_id=version["_id"],
                question=question,
                raw=raw,
                generated_at=generated_at,
            )

        if qtype == "number":
            raw = await self._aggregate(
                build_number_question_pipeline(
                    survey_id, version["_id"], qid
                ),
                comment="survey_stats_question_number",
            )
            return build_number_detail_response(
                survey_id=survey_id,
                version_id=version["_id"],
                question=question,
                raw=raw,
                generated_at=generated_at,
            )

        if qtype == "text":
            skip = (page - 1) * page_size
            raw = await self._aggregate(
                build_text_question_pipeline(
                    survey_id,
                    version["_id"],
                    qid,
                    skip=skip,
                    limit=page_size,
                ),
                comment="survey_stats_question_text",
            )
            return build_text_detail_response(
                survey_id=survey_id,
                version_id=version["_id"],
                question=question,
                raw=raw,
                page=page,
                page_size=page_size,
                generated_at=generated_at,
            )

        raise StatsUnavailableError(
            f"unsupported question type in version: {qtype!r}"
        )


__all__ = [
    "StatsNotFoundError",
    "StatsService",
    "StatsUnavailableError",
    "build_choice_detail_response",
    "build_number_detail_response",
    "build_overview_response",
    "build_text_detail_response",
]
