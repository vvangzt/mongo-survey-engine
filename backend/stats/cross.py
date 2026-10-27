"""Cross-survey statistics for one shared question (phase 2, requirement 8).

Phase 1 statistics always start from ``(survey_id, survey_version_id)`` because a
question had no identity outside one survey version. Now that a question can be
reused, the natural entry point is ``answers.question_ref.entity_id``, which is
covered by a multikey index.

Design note (documented in ``docs/api.md``): these endpoints deliberately do
**not** report an "unanswered rate". Jump logic can hide a question entirely, so
"not displayed" and "skipped" are indistinguishable in the data. Only
answered-side metrics are reported.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from ..questions.schemas import (
    CrossOptionCount,
    CrossQuestionStatsOut,
    CrossTextAnswer,
    CrossTextPageOut,
    CrossVersionBreakdown,
)
from ..questions.service import (
    QuestionLibraryService,
    QuestionNotFoundError,
    QuestionValidationError,
)

MAX_PAGE_SIZE = 100


def _answer_match(
    entity_id: ObjectId,
    version_ids: Sequence[ObjectId] | None,
    survey_ids: Sequence[ObjectId] | None = None,
) -> dict[str, Any]:
    match: dict[str, Any] = {"answers.question_ref.entity_id": entity_id}
    if version_ids is not None:
        match["answers.question_ref.version_id"] = {"$in": list(version_ids)}
    if survey_ids is not None:
        match["survey_id"] = {"$in": list(survey_ids)}
    return match


def _answer_filter(
    entity_id: ObjectId, version_ids: Sequence[ObjectId] | None
) -> dict[str, Any]:
    condition: dict[str, Any] = {
        "answers.question_ref.entity_id": entity_id
    }
    if version_ids is not None:
        condition["answers.question_ref.version_id"] = {"$in": list(version_ids)}
    return condition


def build_cross_overview_pipeline(
    entity_id: ObjectId,
    version_ids: Sequence[ObjectId] | None,
    survey_ids: Sequence[ObjectId] | None = None,
) -> list[dict[str, Any]]:
    """One pass over every response that answered this question, in any survey.

    The multikey index on ``answers.question_ref.entity_id`` narrows the scan
    before ``$unwind``; the post-unwind ``$match`` drops the sibling answers of
    the same document.
    """

    return [
        {"$match": _answer_match(entity_id, version_ids, survey_ids)},
        {"$unwind": "$answers"},
        {"$match": _answer_filter(entity_id, version_ids)},
        {
            "$facet": {
                "answered": [{"$count": "value"}],
                "survey_ids": [{"$group": {"_id": "$survey_id"}}],
                "versions": [
                    {
                        "$group": {
                            "_id": "$answers.question_ref.version_id",
                            "answered_count": {"$sum": 1},
                        }
                    }
                ],
                "options": [
                    {
                        "$match": {
                            "answers.type": {
                                "$in": ["single_choice", "multi_choice"]
                            }
                        }
                    },
                    {"$unwind": "$answers.option_ids"},
                    {
                        "$group": {
                            "_id": {
                                "version_id": "$answers.question_ref.version_id",
                                "option_id": "$answers.option_ids",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "numbers": [
                    {"$match": {"answers.type": "number"}},
                    {
                        "$group": {
                            "_id": None,
                            "count": {"$sum": 1},
                            "average": {"$avg": "$answers.number"},
                            "minimum": {"$min": "$answers.number"},
                            "maximum": {"$max": "$answers.number"},
                        }
                    },
                ],
                "texts": [
                    {"$match": {"answers.type": "text"}},
                    {"$count": "value"},
                ],
            }
        },
    ]


def build_cross_text_pipeline(
    entity_id: ObjectId,
    version_ids: Sequence[ObjectId] | None,
    *,
    skip: int,
    limit: int,
    survey_ids: Sequence[ObjectId] | None = None,
) -> list[dict[str, Any]]:
    if skip < 0:
        raise QuestionValidationError("skip must be >= 0")
    if limit <= 0:
        raise QuestionValidationError("limit must be > 0")

    condition = _answer_filter(entity_id, version_ids)
    condition["answers.type"] = "text"

    return [
        {"$match": _answer_match(entity_id, version_ids, survey_ids)},
        {"$unwind": "$answers"},
        {"$match": condition},
        {"$sort": {"submitted_at": -1, "_id": -1}},
        {
            "$facet": {
                "meta": [{"$count": "value"}],
                "page": [
                    {"$skip": skip},
                    {"$limit": limit},
                    {
                        "$project": {
                            "_id": 0,
                            "text": "$answers.text",
                            "survey_id": 1,
                            "survey_version_id": 1,
                            "submitted_at": 1,
                        }
                    },
                ],
            }
        },
    ]


def _first_count(rows: list[dict[str, Any]] | None) -> int:
    if not rows:
        return 0
    return int(rows[0].get("value") or 0)


class CrossSurveyStatsService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._db = db
        self._responses = db["responses"]
        self._versions = db["question_versions"]
        self._surveys = db["surveys"]
        self._survey_versions = db["survey_versions"]
        self._library = QuestionLibraryService(db)

    # ------------------------------------------------------------------
    # version selection
    # ------------------------------------------------------------------

    async def _select_versions(
        self, user_id: ObjectId, entity_id: ObjectId, version: str | int
    ) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]:
        detail = await self._library.get_question(user_id, entity_id)
        cursor = self._versions.find({"entity_id": entity_id}).sort(
            "version_no", 1
        )
        versions = await cursor.to_list(length=None)
        if not versions:
            raise QuestionNotFoundError("question has no versions")

        if version in ("all", None, ""):
            selected = versions
        elif version == "latest":
            selected = [
                document
                for document in versions
                if str(document["_id"]) == detail.latest_version.id
            ]
        else:
            try:
                number = int(version)
            except (TypeError, ValueError) as exc:
                raise QuestionValidationError(
                    "version must be 'all', 'latest' or a version number"
                ) from exc
            selected = [
                document
                for document in versions
                if document["version_no"] == number
            ]
            if not selected:
                raise QuestionNotFoundError("question version not found")
        return detail, versions, selected

    # ------------------------------------------------------------------
    # overview
    # ------------------------------------------------------------------

    async def overview(
        self,
        user_id: ObjectId,
        entity_id: ObjectId,
        *,
        version: str = "all",
        survey_id: ObjectId | None = None,
    ) -> CrossQuestionStatsOut:
        detail, all_versions, selected = await self._select_versions(
            user_id, entity_id, version
        )
        version_ids = [document["_id"] for document in selected]
        survey_ids = [survey_id] if survey_id is not None else None

        cursor = await self._responses.aggregate(
            build_cross_overview_pipeline(entity_id, version_ids, survey_ids)
        )
        rows = await cursor.to_list(length=1)
        facet = rows[0] if rows else {}

        answered = _first_count(facet.get("answered"))
        survey_count = len(facet.get("survey_ids") or [])
        per_version = {
            str(row["_id"]): int(row["answered_count"])
            for row in facet.get("versions") or []
        }
        numbers = (facet.get("numbers") or [{}])[0] or {}

        latest_version = max(all_versions, key=lambda item: item["version_no"])
        labels = self._labels(all_versions)
        merged = self._merge_options(
            facet.get("options") or [], labels, all_versions, selected
        )

        breakdown = [
            CrossVersionBreakdown(
                version_id=str(document["_id"]),
                version_no=document["version_no"],
                answered_count=per_version.get(str(document["_id"]), 0),
            )
            for document in selected
        ]

        option_sets = {
            tuple(
                sorted(
                    option["option_id"]
                    for option in document["content"].get("options", []) or []
                )
            )
            for document in selected
            if document["content"].get("type")
            in ("single_choice", "multi_choice")
        }

        return CrossQuestionStatsOut(
            entity_id=str(entity_id),
            type=latest_version["content"]["type"],
            title=latest_version["content"]["title"],
            answered_count=answered,
            survey_count=survey_count,
            version_count=len(selected),
            versions=breakdown,
            option_counts=self._order_options(
                merged, latest_version["content"]
            ),
            option_set_mismatch=len(option_sets) > 1,
            merged_by="option_id",
            average=numbers.get("average"),
            minimum=numbers.get("minimum"),
            maximum=numbers.get("maximum"),
            numeric_count=int(numbers.get("count") or 0),
            text_count=_first_count(facet.get("texts")),
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _labels(versions: Sequence[dict[str, Any]]) -> dict[str, str]:
        """Option id -> label, newest version wins."""

        labels: dict[str, str] = {}
        for document in versions:
            for option in document["content"].get("options", []) or []:
                labels[option["option_id"]] = option["label"]
        return labels

    @staticmethod
    def _merge_options(
        rows: Sequence[dict[str, Any]],
        labels: dict[str, str],
        all_versions: Sequence[dict[str, Any]],
        selected: Sequence[dict[str, Any]],
    ) -> list[CrossOptionCount]:
        """Fold per-version option counts into one row per ``option_id``.

        This is only meaningful because option ids are inherited across
        versions of the same question (invariant I6).
        """

        selected_numbers = {
            document["_id"]: document["version_no"] for document in selected
        }
        present_in: dict[str, set[int]] = {}
        for document in all_versions:
            if document["_id"] not in selected_numbers:
                continue
            for option in document["content"].get("options", []) or []:
                present_in.setdefault(option["option_id"], set()).add(
                    document["version_no"]
                )

        merged: dict[str, CrossOptionCount] = {}
        for row in rows:
            option_id = row["_id"]["option_id"]
            count = int(row["count"])
            existing = merged.get(option_id)
            if existing is None:
                merged[option_id] = CrossOptionCount(
                    option_id=option_id,
                    label=labels.get(option_id, option_id),
                    count=count,
                    versions=sorted(present_in.get(option_id, set())),
                )
            else:
                existing.count += count
        return list(merged.values())

    @staticmethod
    def _order_options(
        rows: list[CrossOptionCount], content: dict[str, Any]
    ) -> list[CrossOptionCount]:
        order = [
            option["option_id"]
            for option in content.get("options", []) or []
        ]
        index = {option_id: position for position, option_id in enumerate(order)}
        rows.sort(key=lambda row: (index.get(row.option_id, len(index)), row.option_id))
        return rows

    # ------------------------------------------------------------------
    # text answers
    # ------------------------------------------------------------------

    async def text_page(
        self,
        user_id: ObjectId,
        entity_id: ObjectId,
        *,
        version: str = "all",
        page: int = 1,
        page_size: int = 20,
        survey_id: ObjectId | None = None,
    ) -> CrossTextPageOut:
        if page < 1:
            raise QuestionValidationError("page must be >= 1")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise QuestionValidationError(
                f"page_size must be 1..{MAX_PAGE_SIZE}"
            )
        detail, _all_versions, selected = await self._select_versions(
            user_id, entity_id, version
        )
        if detail.latest_version.content.type != "text":
            raise QuestionValidationError(
                "text answers are only available for text questions"
            )
        version_ids = [document["_id"] for document in selected]
        survey_ids = [survey_id] if survey_id is not None else None
        skip = (page - 1) * page_size

        cursor = await self._responses.aggregate(
            build_cross_text_pipeline(
                entity_id,
                version_ids,
                skip=skip,
                limit=page_size,
                survey_ids=survey_ids,
            )
        )
        rows = await cursor.to_list(length=1)
        facet = rows[0] if rows else {}
        total = _first_count(facet.get("meta"))
        page_rows = facet.get("page") or []

        titles = {
            document["_id"]: document.get("title", "")
            for document in await self._surveys.find(
                {"_id": {"$in": [row["survey_id"] for row in page_rows]}},
                {"title": 1},
            ).to_list(length=None)
        }
        survey_version_numbers = await self._survey_version_numbers(
            [row["survey_version_id"] for row in page_rows]
        )

        answers = [
            CrossTextAnswer(
                text=row["text"],
                survey_id=str(row["survey_id"]),
                survey_title=titles.get(row["survey_id"], ""),
                version_no=survey_version_numbers.get(
                    str(row["survey_version_id"]), 0
                ),
                submitted_at=row["submitted_at"],
            )
            for row in page_rows
        ]
        total_pages = (total + page_size - 1) // page_size if total else 0
        return CrossTextPageOut(
            entity_id=str(entity_id),
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            answers=answers,
            generated_at=datetime.now(timezone.utc),
        )

    async def _survey_version_numbers(
        self, version_ids: Sequence[ObjectId]
    ) -> dict[str, int]:
        unique = list({version_id for version_id in version_ids})
        if not unique:
            return {}
        cursor = self._survey_versions.find(
            {"_id": {"$in": unique}}, {"version_no": 1}
        )
        return {
            str(document["_id"]): document["version_no"]
            for document in await cursor.to_list(length=None)
        }


__all__ = [
    "CrossSurveyStatsService",
    "build_cross_overview_pipeline",
    "build_cross_text_pipeline",
    "MAX_PAGE_SIZE",
]
