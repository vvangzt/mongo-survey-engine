"""Minimal survey authoring, publishing and submission service.

This slice exists so the six required scenarios can be exercised through real
HTTP endpoints against MongoDB. It intentionally implements only the operations
needed by the system tests; production features such as authentication,
collaboration, version cloning and full CRUD are outside this module.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase

from schemas.pydantic import (
    Question,
    SurveyVersion,
    validate_submission,
)

from .schemas import (
    ClosedOut,
    DraftUpdateIn,
    PublishedOut,
    QuestionAddedOut,
    SubmitIn,
    SubmitOut,
    SurveyCreateIn,
    SurveyCreatedOut,
    SurveyDetailOut,
    SurveyListItem,
    SurveyUpdateIn,
    VersionOut,
)


class SurveyNotFoundError(Exception):
    pass


class SurveyConflictError(Exception):
    pass


class SurveyValidationError(Exception):
    pass


class SurveyForbiddenError(Exception):
    pass


class SurveyUnauthenticatedError(Exception):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _version_model(document: dict[str, Any]) -> SurveyVersion:
    return SurveyVersion.model_validate(
        {
            "_id": str(document["_id"]),
            "schema_version": document.get("schema_version", 1),
            "survey_id": str(document["survey_id"]),
            "version_no": document["version_no"],
            "state": document["state"],
            "content_schema_version": document.get(
                "content_schema_version", 1
            ),
            "revision": document["revision"],
            "questions": document.get("questions", []),
            "created_by": str(document["created_by"]),
            "created_at": _utc(document["created_at"]),
            "updated_at": _utc(document["updated_at"]),
            "published_at": (
                _utc(document["published_at"])
                if document.get("published_at")
                else None
            ),
            "content_hash": document.get("content_hash"),
        }
    )


def _canonical_questions(version: SurveyVersion) -> list[dict[str, Any]]:
    return [
        question.model_dump(mode="json", exclude_none=True)
        for question in version.questions
    ]


def _version_out(document: dict[str, Any]) -> VersionOut:
    return VersionOut(
        id=str(document["_id"]),
        version_no=document["version_no"],
        state=document["state"],
        revision=document["revision"],
        questions=document.get("questions", []),
    )


def _list_item(document: dict[str, Any]) -> SurveyListItem:
    return SurveyListItem(
        id=str(document["_id"]),
        slug=document["slug"],
        title=document["title"],
        description=document.get("description", ""),
        status=document["status"],
        allow_anonymous=bool(document.get("allow_anonymous", False)),
        allow_multiple_responses=bool(
            document.get("allow_multiple_responses", True)
        ),
        opens_at=(
            _utc(document["opens_at"]) if document.get("opens_at") else None
        ),
        closes_at=(
            _utc(document["closes_at"]) if document.get("closes_at") else None
        ),
        published_at=(
            _utc(document["published_at"])
            if document.get("published_at")
            else None
        ),
        created_at=_utc(document["created_at"]),
        updated_at=_utc(document["updated_at"]),
    )


class SurveyService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._surveys = db["surveys"]
        self._versions = db["survey_versions"]
        self._responses = db["responses"]

    async def create_survey(
        self, owner_id: ObjectId, payload: SurveyCreateIn
    ) -> SurveyCreatedOut:
        now = datetime.now(timezone.utc)
        opens_at = (
            _utc(payload.opens_at)
            if payload.opens_at is not None
            else now - timedelta(minutes=1)
        )
        closes_at = (
            _utc(payload.closes_at)
            if payload.closes_at is not None
            else now + timedelta(days=365)
        )
        if opens_at >= closes_at:
            raise SurveyValidationError(
                "opens_at must be earlier than closes_at"
            )

        slug = payload.slug or f"s-{uuid.uuid4().hex[:12]}"
        if await self._surveys.find_one({"slug": slug}, {"_id": 1}):
            raise SurveyConflictError("slug already exists")

        survey_id = ObjectId()
        version_id = ObjectId()
        survey = {
            "_id": survey_id,
            "schema_version": 1,
            "owner_id": owner_id,
            "slug": slug,
            "title": payload.title,
            "description": payload.description,
            "status": "draft",
            "allow_anonymous": payload.allow_anonymous,
            "allow_multiple_responses": payload.allow_multiple_responses,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "current_draft_version_id": version_id,
            "published_version_id": None,
            "last_version_no": 1,
            "published_at": None,
            "closed_at": None,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        version = {
            "_id": version_id,
            "schema_version": 1,
            "survey_id": survey_id,
            "version_no": 1,
            "state": "draft",
            "content_schema_version": 1,
            "revision": 1,
            "questions": [],
            "created_by": owner_id,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            "content_hash": None,
        }

        try:
            await self._surveys.insert_one(survey)
        except DuplicateKeyError as exc:
            raise SurveyConflictError("slug already exists") from exc
        try:
            await self._versions.insert_one(version)
        except Exception:
            await self._surveys.delete_one({"_id": survey_id})
            raise

        return SurveyCreatedOut(
            id=str(survey_id),
            slug=slug,
            title=payload.title,
            status="draft",
            allow_anonymous=payload.allow_anonymous,
            allow_multiple_responses=payload.allow_multiple_responses,
            current_draft_version_id=str(version_id),
            created_at=now,
        )

    async def list_surveys(
        self, owner_id: ObjectId
    ) -> list[SurveyListItem]:
        cursor = (
            self._surveys.find(
                {"owner_id": owner_id, "deleted_at": None}
            )
            .sort("updated_at", -1)
            .limit(200)
        )
        documents = await cursor.to_list(length=200)
        return [_list_item(document) for document in documents]

    async def get_survey(
        self, owner_id: ObjectId, survey_id: ObjectId
    ) -> SurveyDetailOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")

        current_draft = None
        if survey.get("current_draft_version_id"):
            draft_doc = await self._versions.find_one(
                {
                    "_id": survey["current_draft_version_id"],
                    "survey_id": survey_id,
                    "state": "draft",
                }
            )
            if draft_doc is not None:
                current_draft = _version_out(draft_doc)

        published_version = None
        if survey.get("published_version_id"):
            published_doc = await self._versions.find_one(
                {
                    "_id": survey["published_version_id"],
                    "survey_id": survey_id,
                    "state": "published",
                }
            )
            if published_doc is not None:
                published_version = _version_out(published_doc)

        item = _list_item(survey)
        return SurveyDetailOut(
            **item.model_dump(),
            current_draft=current_draft,
            published_version=published_version,
        )

    async def update_survey(
        self,
        owner_id: ObjectId,
        survey_id: ObjectId,
        payload: SurveyUpdateIn,
    ) -> SurveyDetailOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return await self.get_survey(owner_id, survey_id)

        if "opens_at" in changes and changes["opens_at"] is not None:
            changes["opens_at"] = _utc(changes["opens_at"])
        if "closes_at" in changes and changes["closes_at"] is not None:
            changes["closes_at"] = _utc(changes["closes_at"])

        opens_at = changes.get("opens_at", survey.get("opens_at"))
        closes_at = changes.get("closes_at", survey.get("closes_at"))
        if (
            opens_at is not None
            and closes_at is not None
            and _utc(opens_at) >= _utc(closes_at)
        ):
            raise SurveyValidationError(
                "opens_at must be earlier than closes_at"
            )

        changes["updated_at"] = datetime.now(timezone.utc)
        await self._surveys.update_one(
            {"_id": survey_id, "owner_id": owner_id},
            {"$set": changes},
        )
        return await self.get_survey(owner_id, survey_id)

    async def close_survey(
        self, owner_id: ObjectId, survey_id: ObjectId
    ) -> ClosedOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") == "draft":
            raise SurveyConflictError("a draft survey cannot be closed")
        if survey.get("current_draft_version_id"):
            raise SurveyConflictError(
                "publish or discard the pending new version before closing"
            )
        if survey.get("status") == "closed" and survey.get("closed_at"):
            return ClosedOut(
                id=str(survey_id),
                status="closed",
                closed_at=_utc(survey["closed_at"]),
            )

        now = datetime.now(timezone.utc)
        await self._surveys.update_one(
            {"_id": survey_id, "owner_id": owner_id},
            {
                "$set": {
                    "status": "closed",
                    "closed_at": now,
                    "updated_at": now,
                }
            },
        )
        return ClosedOut(
            id=str(survey_id),
            status="closed",
            closed_at=now,
        )

    async def add_question(
        self,
        owner_id: ObjectId,
        survey_id: ObjectId,
        question: Question,
    ) -> QuestionAddedOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") != "draft":
            raise SurveyConflictError(
                "questions can only be added to a draft survey"
            )
        version_id = survey.get("current_draft_version_id")
        if version_id is None:
            raise SurveyConflictError("survey has no editable draft version")

        version = await self._versions.find_one(
            {"_id": version_id, "survey_id": survey_id, "state": "draft"}
        )
        if version is None:
            raise SurveyConflictError("editable draft version not found")
        if any(
            item.get("question_id") == question.question_id
            for item in version.get("questions", [])
        ):
            raise SurveyConflictError(
                f"question already exists: {question.question_id}"
            )

        now = datetime.now(timezone.utc)
        question_doc = question.model_dump(mode="json", exclude_none=True)
        updated = await self._versions.find_one_and_update(
            {
                "_id": version_id,
                "state": "draft",
                "questions.question_id": {"$ne": question.question_id},
            },
            {
                "$push": {"questions": question_doc},
                "$inc": {"revision": 1},
                "$set": {"updated_at": now},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise SurveyConflictError("draft changed concurrently")
        await self._surveys.update_one(
            {"_id": survey_id}, {"$set": {"updated_at": now}}
        )
        return QuestionAddedOut(
            survey_id=str(survey_id),
            survey_version_id=str(version_id),
            revision=updated["revision"],
            question=question,
        )

    async def create_new_draft(
        self, owner_id: ObjectId, survey_id: ObjectId
    ) -> VersionOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") == "closed":
            raise SurveyConflictError("closed surveys cannot be edited")
        if survey.get("status") == "draft":
            raise SurveyConflictError(
                "a draft survey already has an editable version"
            )

        if survey.get("current_draft_version_id"):
            existing = await self._versions.find_one(
                {
                    "_id": survey["current_draft_version_id"],
                    "survey_id": survey_id,
                    "state": "draft",
                }
            )
            if existing is not None:
                return _version_out(existing)
            raise SurveyConflictError("survey has an inconsistent draft pointer")

        published_version_id = survey.get("published_version_id")
        if published_version_id is None:
            raise SurveyConflictError("survey has no published version")
        published = await self._versions.find_one(
            {
                "_id": published_version_id,
                "survey_id": survey_id,
                "state": "published",
            }
        )
        if published is None:
            raise SurveyConflictError("published version is unavailable")

        now = datetime.now(timezone.utc)
        version_no = int(survey.get("last_version_no", 0)) + 1
        version_id = ObjectId()
        version_document = {
            "_id": version_id,
            "schema_version": 1,
            "survey_id": survey_id,
            "version_no": version_no,
            "state": "draft",
            "content_schema_version": published.get(
                "content_schema_version", 1
            ),
            "revision": 1,
            "questions": published.get("questions", []),
            "created_by": owner_id,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            "content_hash": None,
        }
        try:
            await self._versions.insert_one(version_document)
        except DuplicateKeyError as exc:
            raise SurveyConflictError(
                "a new version was created concurrently"
            ) from exc

        result = await self._surveys.update_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "status": "published",
                "current_draft_version_id": None,
            },
            {
                "$set": {
                    "current_draft_version_id": version_id,
                    "last_version_no": version_no,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count != 1:
            await self._versions.delete_one({"_id": version_id})
            raise SurveyConflictError(
                "survey changed while creating a new draft; retry is safe"
            )
        return _version_out(version_document)

    async def replace_draft(
        self,
        owner_id: ObjectId,
        survey_id: ObjectId,
        payload: DraftUpdateIn,
    ) -> VersionOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") not in ("draft", "published"):
            raise SurveyConflictError(
                "closed surveys cannot be edited"
            )
        version_id = survey.get("current_draft_version_id")
        if version_id is None:
            raise SurveyConflictError("survey has no editable draft version")

        questions = [
            question.model_dump(mode="json", exclude_none=True)
            for question in payload.questions
        ]
        now = datetime.now(timezone.utc)
        updated = await self._versions.find_one_and_update(
            {
                "_id": version_id,
                "survey_id": survey_id,
                "state": "draft",
                "revision": payload.revision,
            },
            {
                "$set": {"questions": questions, "updated_at": now},
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            fresh = await self._versions.find_one(
                {"_id": version_id, "survey_id": survey_id}
            )
            if fresh is not None and fresh.get("revision") != payload.revision:
                raise SurveyConflictError(
                    "draft revision changed; reload before saving"
                )
            raise SurveyConflictError("draft is not editable")
        await self._surveys.update_one(
            {"_id": survey_id, "owner_id": owner_id},
            {"$set": {"updated_at": now}},
        )
        return _version_out(updated)

    async def publish_survey(
        self, owner_id: ObjectId, survey_id: ObjectId
    ) -> PublishedOut:
        survey = await self._surveys.find_one(
            {
                "_id": survey_id,
                "owner_id": owner_id,
                "deleted_at": None,
            }
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") == "closed":
            raise SurveyConflictError("survey is closed")

        # Idempotent: repeating publish with no pending draft returns the same
        # publication. A pending draft means this is a new version.
        if (
            survey.get("status") == "published"
            and survey.get("current_draft_version_id") is None
        ):
            version_id = survey.get("published_version_id")
            if version_id is None:
                raise SurveyConflictError(
                    "published survey is missing its published version"
                )
            version = await self._versions.find_one(
                {
                    "_id": version_id,
                    "survey_id": survey_id,
                    "state": "published",
                }
            )
            if version is None or not version.get("published_at"):
                raise SurveyConflictError(
                    "published version metadata is incomplete"
                )
            return PublishedOut(
                survey_id=str(survey_id),
                survey_version_id=str(version_id),
                version_no=version["version_no"],
                slug=survey["slug"],
                status="published",
                published_at=_utc(version["published_at"]),
            )

        if survey.get("status") not in ("draft", "published"):
            raise SurveyConflictError("survey is not editable")

        version_id = survey.get("current_draft_version_id")
        if version_id is None:
            raise SurveyConflictError("survey has no draft version")

        version = await self._versions.find_one(
            {"_id": version_id, "survey_id": survey_id}
        )
        if version is None:
            raise SurveyConflictError("draft version not found")

        if version.get("state") == "draft":
            try:
                version_model = _version_model(version)
            except ValidationError as exc:
                raise SurveyValidationError(
                    f"survey version is invalid: {exc}"
                ) from exc

            canonical = json.dumps(
                _canonical_questions(version_model),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            content_hash = hashlib.sha256(canonical).hexdigest()
            published_at = datetime.now(timezone.utc)

            updated_version = await self._versions.update_one(
                {"_id": version_id, "state": "draft"},
                {
                    "$set": {
                        "state": "published",
                        "published_at": published_at,
                        "content_hash": content_hash,
                        "updated_at": published_at,
                    }
                },
            )
            if updated_version.modified_count == 1:
                version = {
                    **version,
                    "state": "published",
                    "published_at": published_at,
                    "content_hash": content_hash,
                }
            else:
                # Another request won the version transition. It is safe to
                # continue only if the version is now published.
                version = await self._versions.find_one(
                    {"_id": version_id, "survey_id": survey_id}
                )
                if version is None or version.get("state") != "published":
                    raise SurveyConflictError(
                        "draft changed during publication"
                    )

        if version.get("state") != "published":
            raise SurveyConflictError("draft version cannot be published")
        if not version.get("published_at") or not version.get("content_hash"):
            raise SurveyConflictError(
                "published version metadata is incomplete"
            )

        try:
            version_model = _version_model(version)
        except ValidationError as exc:
            raise SurveyValidationError(
                f"published version is invalid: {exc}"
            ) from exc

        published_at = _utc(version["published_at"])
        updated_survey = await self._surveys.update_one(
            {
                "_id": survey_id,
                "status": {"$in": ["draft", "published"]},
                "current_draft_version_id": version_id,
            },
            {
                "$set": {
                    "status": "published",
                    "published_version_id": version_id,
                    "published_at": published_at,
                    "current_draft_version_id": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if updated_survey.modified_count != 1:
            fresh = await self._surveys.find_one(
                {"_id": survey_id, "owner_id": owner_id}
            )
            if (
                fresh is not None
                and fresh.get("status") == "published"
                and fresh.get("published_version_id") == version_id
            ):
                return PublishedOut(
                    survey_id=str(survey_id),
                    survey_version_id=str(version_id),
                    version_no=version_model.version_no,
                    slug=fresh["slug"],
                    status="published",
                    published_at=published_at,
                )
            raise SurveyConflictError(
                "survey changed during publication; retry is safe"
            )

        return PublishedOut(
            survey_id=str(survey_id),
            survey_version_id=str(version_id),
            version_no=version_model.version_no,
            slug=survey["slug"],
            status="published",
            published_at=published_at,
        )

    async def submit_response(
        self,
        survey_id: ObjectId,
        payload: SubmitIn,
        user_id: ObjectId | None,
    ) -> SubmitOut:
        survey = await self._surveys.find_one(
            {"_id": survey_id, "deleted_at": None}
        )
        if survey is None:
            raise SurveyNotFoundError("survey not found")
        if survey.get("status") != "published":
            raise SurveyConflictError("survey is not published")

        now = datetime.now(timezone.utc)
        opens_at = survey.get("opens_at")
        closes_at = survey.get("closes_at")
        if opens_at is not None and now < _utc(opens_at):
            raise SurveyConflictError("survey is not open yet")
        if closes_at is not None and now > _utc(closes_at):
            raise SurveyConflictError("survey has closed")

        if payload.is_anonymous:
            if not survey.get("allow_anonymous", False):
                raise SurveyForbiddenError(
                    "this survey does not allow anonymous submissions"
                )
            respondent_id = None
        else:
            if user_id is None:
                raise SurveyUnauthenticatedError(
                    "authentication required for identified submission"
                )
            respondent_id = user_id

        if (
            respondent_id is not None
            and not survey.get("allow_multiple_responses", True)
        ):
            previous = await self._responses.find_one(
                {
                    "survey_id": survey_id,
                    "respondent_id": respondent_id,
                },
                {"_id": 1},
            )
            if previous is not None:
                raise SurveyConflictError(
                    "this survey allows only one response per user"
                )

        version_id = survey.get("published_version_id")
        if version_id is None:
            raise SurveyConflictError("survey has no published version")
        version = await self._versions.find_one(
            {"_id": version_id, "survey_id": survey_id, "state": "published"}
        )
        if version is None:
            raise SurveyConflictError("published version is unavailable")

        try:
            version_model = _version_model(version)
        except ValidationError as exc:
            raise SurveyConflictError(
                "published version cannot be interpreted"
            ) from exc

        result = validate_submission(version_model, payload.answers)

        duplicate = await self._responses.find_one(
            {
                "survey_id": survey_id,
                "submission_token": payload.submission_token,
            },
            {"_id": 1},
        )
        if duplicate is not None:
            raise SurveyConflictError("submission_token already used")

        response_id = ObjectId()
        try:
            await self._responses.insert_one(
                {
                    "_id": response_id,
                    "schema_version": 1,
                    "survey_id": survey_id,
                    "survey_version_id": version_id,
                    "respondent_id": respondent_id,
                    "is_anonymous": payload.is_anonymous,
                    "submission_token": payload.submission_token,
                    "answers": [
                        answer.model_dump(mode="json", exclude_none=True)
                        for answer in result.answers
                    ],
                    "submitted_at": now,
                }
            )
        except DuplicateKeyError as exc:
            raise SurveyConflictError("duplicate submission") from exc

        return SubmitOut(
            response_id=str(response_id),
            survey_id=str(survey_id),
            survey_version_id=str(version_id),
            is_anonymous=payload.is_anonymous,
            submitted_at=now,
            question_path=list(result.path),
        )


__all__ = [
    "SurveyConflictError",
    "SurveyForbiddenError",
    "SurveyNotFoundError",
    "SurveyService",
    "SurveyUnauthenticatedError",
    "SurveyValidationError",
]
