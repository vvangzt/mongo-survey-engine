"""Native MongoDB aggregation pipelines for survey statistics.

All pipelines start with equality matches on
``(survey_id, survey_version_id)`` so the compound index can narrow the scan
before any ``$unwind``. Statistics are always scoped to one immutable survey
version; option labels and question order are applied by the service layer from
the version definition.
"""

from __future__ import annotations

from typing import Any, Literal

from bson import ObjectId

ChoiceType = Literal["single_choice", "multi_choice"]
QuestionType = Literal["single_choice", "multi_choice", "text", "number"]

CHOICE_TYPES = ["single_choice", "multi_choice"]


def _base_match(survey_id: ObjectId, version_id: ObjectId) -> dict[str, Any]:
    return {
        "$match": {
            "survey_id": survey_id,
            "survey_version_id": version_id,
        }
    }


def build_overview_pipeline(
    survey_id: ObjectId, version_id: ObjectId
) -> list[dict[str, Any]]:
    """One pass per facet over all responses of a version.

    The five branches compute:
    - all submitted responses (including submissions with no answers);
    - answered counts for choice questions;
    - option frequencies for single/multi choice;
    - count/average/min/max for number questions;
    - answered counts for text questions (text bodies are fetched separately).
    """

    return [
        _base_match(survey_id, version_id),
        {
            "$facet": {
                "response_count": [{"$count": "value"}],
                "choice_answered": [
                    {"$unwind": "$answers"},
                    {"$match": {"answers.type": {"$in": CHOICE_TYPES}}},
                    {
                        "$group": {
                            "_id": "$answers.question_id",
                            "answered_count": {"$sum": 1},
                        }
                    },
                ],
                "choice_options": [
                    {"$unwind": "$answers"},
                    {"$match": {"answers.type": {"$in": CHOICE_TYPES}}},
                    {"$unwind": "$answers.option_ids"},
                    {
                        "$group": {
                            "_id": {
                                "question_id": "$answers.question_id",
                                "option_id": "$answers.option_ids",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "number_stats": [
                    {"$unwind": "$answers"},
                    {"$match": {"answers.type": "number"}},
                    {
                        "$group": {
                            "_id": "$answers.question_id",
                            "answered_count": {"$sum": 1},
                            "average": {"$avg": "$answers.number"},
                            "minimum": {"$min": "$answers.number"},
                            "maximum": {"$max": "$answers.number"},
                        }
                    },
                ],
                "text_stats": [
                    {"$unwind": "$answers"},
                    {"$match": {"answers.type": "text"}},
                    {
                        "$group": {
                            "_id": "$answers.question_id",
                            "answered_count": {"$sum": 1},
                        }
                    },
                ],
            }
        },
    ]


def _question_prefilter(
    survey_id: ObjectId,
    version_id: ObjectId,
    qid: str,
    answer_type: QuestionType,
) -> list[dict[str, Any]]:
    """Extract exactly one answer from each response before counting.

    ``answers.question_id`` is indexed as part of
    ``(survey_id, survey_version_id, answers.question_id)``. After narrowing the
    documents, $filter avoids unwinding every answer of every matching response.
    """

    return [
        {
            "$match": {
                "survey_id": survey_id,
                "survey_version_id": version_id,
                "answers.question_id": qid,
            }
        },
        {
            "$set": {
                "_answer": {
                    "$arrayElemAt": [
                        {
                            "$filter": {
                                "input": "$answers",
                                "as": "answer",
                                "cond": {
                                    "$eq": ["$$answer.question_id", qid]
                                },
                            }
                        },
                        0,
                    ]
                }
            }
        },
        {"$match": {"_answer.type": answer_type}},
    ]


def build_choice_question_pipeline(
    survey_id: ObjectId,
    version_id: ObjectId,
    qid: str,
    answer_type: ChoiceType,
) -> list[dict[str, Any]]:
    """Count answered respondents and option frequency for one choice question."""

    if answer_type not in CHOICE_TYPES:
        raise ValueError(f"invalid choice answer type: {answer_type}")

    return [
        *_question_prefilter(survey_id, version_id, qid, answer_type),
        {
            "$facet": {
                "answered": [{"$count": "value"}],
                "options": [
                    {"$unwind": "$_answer.option_ids"},
                    {
                        "$group": {
                            "_id": "$_answer.option_ids",
                            "count": {"$sum": 1},
                        }
                    },
                ],
            }
        },
    ]


def build_number_question_pipeline(
    survey_id: ObjectId, version_id: ObjectId, qid: str
) -> list[dict[str, Any]]:
    """Compute count, average, minimum and maximum for one number question."""

    return [
        *_question_prefilter(survey_id, version_id, qid, "number"),
        {
            "$facet": {
                "stats": [
                    {
                        "$group": {
                            "_id": None,
                            "answered_count": {"$sum": 1},
                            "average": {"$avg": "$_answer.number"},
                            "minimum": {"$min": "$_answer.number"},
                            "maximum": {"$max": "$_answer.number"},
                        }
                    }
                ]
            }
        },
    ]


def build_text_question_pipeline(
    survey_id: ObjectId,
    version_id: ObjectId,
    qid: str,
    *,
    skip: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Return total text-answer count and a deterministic page of text values.

    Sorting is newest-first with ``_id`` as a tie-breaker. Offset pagination is
    simple and adequate for owner dashboards; for very large exports a
    cursor-based endpoint should be preferred.
    """

    if skip < 0:
        raise ValueError("skip must be >= 0")
    if limit <= 0:
        raise ValueError("limit must be > 0")

    return [
        *_question_prefilter(survey_id, version_id, qid, "text"),
        {
            "$facet": {
                "meta": [{"$count": "value"}],
                "page": [
                    {"$sort": {"submitted_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": limit},
                    {
                        "$project": {
                            "_id": 0,
                            "text": "$_answer.text",
                            "submitted_at": 1,
                        }
                    },
                ],
            }
        },
    ]


__all__ = [
    "ChoiceType",
    "QuestionType",
    "build_choice_question_pipeline",
    "build_number_question_pipeline",
    "build_overview_pipeline",
    "build_text_question_pipeline",
]
