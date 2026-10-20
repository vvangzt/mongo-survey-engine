"""Public survey lookup, interactive branch advancement and slug submission."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase

from schemas.pydantic import Answer, Question, SurveyVersion, advance_survey

from .public_schemas import (
    AdvanceIn,
    AdvanceOut,
    PublicQuestion,
    PublicSurveyOut,
)
from .schemas import SubmitIn, SubmitOut
from .service import (
    SurveyConflictError,
    SurveyNotFoundError,
    SurveyService,
    SurveyUnauthenticatedError,
    _utc,
    _version_model,
)


def _public_question(question: Question) -> PublicQuestion:
    data = question.model_dump(mode="json", exclude_none=True)
    data.pop("logic", None)
    return PublicQuestion.model_validate(data)


class PublicSurveyService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._surveys = db["surveys"]
        self._versions = db["survey_versions"]
        self._submission_service = SurveyService(db)

    async def _find_published(
        self, slug: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        survey = await self._surveys.find_one(
            {"slug": slug, "deleted_at": None}
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") not in ("published", "closed"):
            # A draft is not a public object.
            raise SurveyNotFoundError("survey not found")
        version_id = survey.get("published_version_id")
        if version_id is None:
            raise SurveyNotFoundError("survey not found")
        version = await self._versions.find_one(
            {
                "_id": version_id,
                "survey_id": survey["_id"],
                "state": "published",
            }
        )
        if version is None:
            raise SurveyConflictError("published version is unavailable")
        return survey, version

    @staticmethod
    def _is_open(survey: dict[str, Any], now: datetime) -> bool:
        if survey.get("status") != "published":
            return False
        opens_at = survey.get("opens_at")
        closes_at = survey.get("closes_at")
        if opens_at is not None and now < _utc(opens_at):
            return False
        if closes_at is not None and now > _utc(closes_at):
            return False
        return True

    @staticmethod
    def _require_identity(
        survey: dict[str, Any], user_id: ObjectId | None
    ) -> None:
        if not survey.get("allow_anonymous", False) and user_id is None:
            raise SurveyUnauthenticatedError(
                "authentication required to open this survey"
            )

    async def get_by_slug(self, slug: str) -> PublicSurveyOut:
        survey, version = await self._find_published(slug)
        now = datetime.now(timezone.utc)
        return PublicSurveyOut(
            id=str(survey["_id"]),
            slug=survey["slug"],
            title=survey["title"],
            description=survey.get("description", ""),
            status=survey["status"],
            allow_anonymous=bool(survey.get("allow_anonymous", False)),
            allow_multiple_responses=bool(
                survey.get("allow_multiple_responses", True)
            ),
            requires_login=not bool(survey.get("allow_anonymous", False)),
            is_open=self._is_open(survey, now),
            opens_at=(
                _utc(survey["opens_at"])
                if survey.get("opens_at")
                else None
            ),
            closes_at=(
                _utc(survey["closes_at"])
                if survey.get("closes_at")
                else None
            ),
            version_no=version["version_no"],
        )

    async def advance(
        self,
        slug: str,
        payload: AdvanceIn,
        user_id: ObjectId | None,
    ) -> AdvanceOut:
        survey, version = await self._find_published(slug)
        if not self._is_open(survey, datetime.now(timezone.utc)):
            raise SurveyConflictError("survey is not open for responses")
        self._require_identity(survey, user_id)

        try:
            version_model: SurveyVersion = _version_model(version)
        except ValidationError as exc:
            raise SurveyConflictError(
                "published version cannot be interpreted"
            ) from exc

        result = advance_survey(
            version_model,
            payload.answers,
            skipped_question_ids=payload.skipped_question_ids,
        )
        next_question = (
            _public_question(result.next_question)
            if result.next_question is not None
            else None
        )
        return AdvanceOut(
            survey_id=str(survey["_id"]),
            survey_version_id=str(version["_id"]),
            next_question=next_question,
            completed=result.completed,
            path=list(result.path),
            version_no=version_model.version_no,
        )

    async def submit(
        self,
        slug: str,
        payload: SubmitIn,
        user_id: ObjectId | None,
    ) -> SubmitOut:
        survey, _version = await self._find_published(slug)
        return await self._submission_service.submit_response(
            survey["_id"], payload, user_id
        )


__all__ = ["PublicSurveyService"]
