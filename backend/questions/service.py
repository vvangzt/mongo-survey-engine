"""Service layer for the shared question library (phase 2).

Vocabulary used throughout:

``entity``   a ``questions`` document: stable identity, owner, visibility
``version``  a ``question_versions`` document: immutable content, v1 -> v2 -> v3
``share``    a ``question_shares`` grant from the owner to another user
``library``  a ``question_libraries`` document (a named question bank)
``item``     a ``question_library_items`` membership

Permission model (deliberately identical in spirit to the survey rules):

* **read**  owner, or a share exists, or ``visibility == public``;
* **use**   owner, or the share permission is ``use``, or public;
* **write** owner only;
* unauthorised access raises *not found* rather than *forbidden* so the API
  does not leak the existence of other users' questions.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from schemas.pydantic import (
    LibraryVisibility,
    QuestionContent,
    QuestionVisibility,
    SharePermission,
    canonical_content,
    hash_content,
    merge_option_ids,
)
from schemas.pydantic.models import Option, QuestionRef

from .schemas import (
    LibraryCreateIn,
    LibraryDetailOut,
    LibraryItemIn,
    LibraryItemOut,
    LibraryOut,
    LibraryUpdateIn,
    QuestionCreateIn,
    QuestionDetailOut,
    QuestionForkIn,
    QuestionForkIn as _QuestionForkIn,
    QuestionSummary,
    QuestionUsageOut,
    QuestionVersionIn,
    QuestionVersionOut,
    ShareGrantIn,
    ShareOut,
)

SCOPE_MINE = "mine"
SCOPE_SHARED = "shared"
SCOPE_PUBLIC = "public"
SCOPE_USABLE = "usable"
SCOPE_LIBRARY = "library"
SCOPES = (SCOPE_MINE, SCOPE_SHARED, SCOPE_PUBLIC, SCOPE_USABLE, SCOPE_LIBRARY)

MAX_LIST = 200


class QuestionNotFoundError(Exception):
    pass


class QuestionConflictError(Exception):
    pass


class QuestionValidationError(Exception):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _new_instance_id() -> str:
    return f"q_lib_{uuid.uuid4().hex[:12]}"


class QuestionLibraryService:
    def __init__(self, db: AsyncDatabase) -> None:
        self._db = db
        self._questions = db["questions"]
        self._versions = db["question_versions"]
        self._shares = db["question_shares"]
        self._libraries = db["question_libraries"]
        self._items = db["question_library_items"]
        self._surveys = db["surveys"]
        self._survey_versions = db["survey_versions"]
        self._users = db["users"]

    # ------------------------------------------------------------------
    # access control
    # ------------------------------------------------------------------

    async def _permissions(
        self, user_id: ObjectId, entity_ids: Sequence[ObjectId]
    ) -> dict[ObjectId, str]:
        if not entity_ids:
            return {}
        cursor = self._shares.find(
            {"grantee_id": user_id, "entity_id": {"$in": list(entity_ids)}},
            {"entity_id": 1, "permission": 1},
        )
        return {
            document["entity_id"]: document["permission"]
            for document in await cursor.to_list(length=None)
        }

    async def _permission(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> str | None:
        document = await self._shares.find_one(
            {"grantee_id": user_id, "entity_id": entity_id},
            {"permission": 1},
        )
        return document["permission"] if document else None

    @staticmethod
    def _can_read(
        entity: dict[str, Any], user_id: ObjectId, permission: str | None
    ) -> bool:
        if entity["owner_id"] == user_id:
            return True
        if permission is not None:
            return True
        return entity.get("visibility") == QuestionVisibility.public.value

    @staticmethod
    def _can_use(
        entity: dict[str, Any], user_id: ObjectId, permission: str | None
    ) -> bool:
        if entity["owner_id"] == user_id:
            return True
        if permission == SharePermission.use.value:
            return True
        return entity.get("visibility") == QuestionVisibility.public.value

    async def _require_entity(
        self,
        entity_id: ObjectId,
        *,
        user_id: ObjectId,
        require_owner: bool = False,
        require_use: bool = False,
    ) -> dict[str, Any]:
        entity = await self._questions.find_one({"_id": entity_id})
        if entity is None or entity.get("deleted_at") is not None:
            raise QuestionNotFoundError("question not found")
        if require_owner:
            if entity["owner_id"] != user_id:
                raise QuestionNotFoundError("question not found")
            return entity
        permission = await self._permission(user_id, entity_id)
        allowed = (
            self._can_use(entity, user_id, permission)
            if require_use
            else self._can_read(entity, user_id, permission)
        )
        if not allowed:
            raise QuestionNotFoundError("question not found")
        return entity

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _version_out(document: dict[str, Any]) -> QuestionVersionOut:
        return QuestionVersionOut(
            id=str(document["_id"]),
            entity_id=str(document["entity_id"]),
            version_no=document["version_no"],
            parent_version_id=(
                str(document["parent_version_id"])
                if document.get("parent_version_id")
                else None
            ),
            restored_from_version_id=(
                str(document["restored_from_version_id"])
                if document.get("restored_from_version_id")
                else None
            ),
            content=document["content"],
            content_hash=document["content_hash"],
            created_at=_utc(document["created_at"]),
        )

    async def _usernames(
        self, user_ids: Iterable[ObjectId]
    ) -> dict[ObjectId, str]:
        unique = list({user_id for user_id in user_ids})
        if not unique:
            return {}
        cursor = self._users.find(
            {"_id": {"$in": unique}}, {"username": 1}
        )
        return {
            document["_id"]: document["username"]
            for document in await cursor.to_list(length=None)
        }

    async def _summary(
        self,
        entity: dict[str, Any],
        user_id: ObjectId,
        username: str | None,
    ) -> QuestionSummary:
        is_owner = entity["owner_id"] == user_id
        return QuestionSummary(
            id=str(entity["_id"]),
            owner_id=str(entity["owner_id"]),
            owner_username=username,
            type=entity["type"],
            title=entity["title"],
            visibility=entity.get("visibility", "private"),
            latest_version_no=entity["latest_version_no"],
            version_count=entity["version_count"],
            created_at=_utc(entity["created_at"]),
            updated_at=_utc(entity["updated_at"]),
            is_owner=is_owner,
            can_edit=is_owner,
        )

    # ------------------------------------------------------------------
    # questions: create / read / list
    # ------------------------------------------------------------------

    async def create_question(
        self, owner_id: ObjectId, payload: QuestionCreateIn
    ) -> QuestionDetailOut:
        now = datetime.now(timezone.utc)
        entity_id = ObjectId()
        version_id = ObjectId()
        content = payload.content
        digest = hash_content(content)

        entity = {
            "_id": entity_id,
            "schema_version": 1,
            "owner_id": owner_id,
            "root_entity_id": entity_id,
            "source_entity_id": None,
            "source_version_id": None,
            "lineage_depth": 0,
            "type": content.type,
            "title": content.title,
            "visibility": payload.visibility.value,
            "latest_version_id": version_id,
            "latest_version_no": 1,
            "version_count": 1,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        version = {
            "_id": version_id,
            "schema_version": 1,
            "entity_id": entity_id,
            "version_no": 1,
            "parent_version_id": None,
            "restored_from_version_id": None,
            "content": canonical_content(content),
            "content_hash": digest,
            "created_by": owner_id,
            "created_at": now,
            "legacy_key": None,
        }
        await self._questions.insert_one(entity)
        try:
            await self._versions.insert_one(version)
        except Exception:
            await self._questions.delete_one({"_id": entity_id})
            raise

        usernames = await self._usernames([owner_id])
        return await self._detail(
            entity, owner_id, usernames.get(owner_id)
        )

    async def list_questions(
        self,
        user_id: ObjectId,
        *,
        scope: str = SCOPE_USABLE,
        type_filter: str | None = None,
        text: str | None = None,
        limit: int = MAX_LIST,
    ) -> list[QuestionSummary]:
        if scope not in SCOPES:
            raise QuestionValidationError(f"unsupported scope: {scope}")

        query: dict[str, Any] = {"deleted_at": None}
        if scope == SCOPE_MINE:
            query["owner_id"] = user_id
        elif scope == SCOPE_SHARED:
            query["_id"] = {"$in": await self._shared_entity_ids(user_id)}
        elif scope == SCOPE_PUBLIC:
            query["visibility"] = QuestionVisibility.public.value
        elif scope == SCOPE_LIBRARY:
            query["_id"] = {"$in": await self._library_entity_ids(user_id)}
        else:  # usable = mine + shared + public
            shared = await self._shared_entity_ids(user_id)
            query["$or"] = [
                {"owner_id": user_id},
                {"_id": {"$in": shared}},
                {"visibility": QuestionVisibility.public.value},
            ]

        if type_filter:
            query["type"] = type_filter
        if text:
            query["title"] = {"$regex": re.escape(text), "$options": "i"}

        cursor = (
            self._questions.find(query)
            .sort("updated_at", -1)
            .limit(max(1, min(limit, MAX_LIST)))
        )
        documents = await cursor.to_list(length=None)
        usernames = await self._usernames(
            document["owner_id"] for document in documents
        )
        return [
            await self._summary(
                document, user_id, usernames.get(document["owner_id"])
            )
            for document in documents
        ]

    async def _shared_entity_ids(self, user_id: ObjectId) -> list[ObjectId]:
        cursor = self._shares.find(
            {"grantee_id": user_id}, {"entity_id": 1}
        )
        return [
            document["entity_id"]
            for document in await cursor.to_list(length=None)
        ]

    async def _library_entity_ids(self, user_id: ObjectId) -> list[ObjectId]:
        library_cursor = self._libraries.find(
            {
                "$or": [
                    {"owner_id": user_id},
                    {"visibility": LibraryVisibility.public.value},
                ]
            },
            {"_id": 1},
        )
        library_ids = [
            document["_id"]
            for document in await library_cursor.to_list(length=None)
        ]
        if not library_ids:
            return []
        item_cursor = self._items.find(
            {"library_id": {"$in": library_ids}}, {"entity_id": 1}
        )
        return list(
            {
                document["entity_id"]
                for document in await item_cursor.to_list(length=None)
            }
        )

    async def get_question(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> QuestionDetailOut:
        entity = await self._require_entity(entity_id, user_id=user_id)
        usernames = await self._usernames([entity["owner_id"]])
        return await self._detail(
            entity, user_id, usernames.get(entity["owner_id"])
        )

    async def _detail(
        self,
        entity: dict[str, Any],
        user_id: ObjectId,
        owner_username: str | None,
    ) -> QuestionDetailOut:
        version_cursor = self._versions.find(
            {"entity_id": entity["_id"]}
        ).sort("version_no", -1)
        versions = await version_cursor.to_list(length=None)
        summary = await self._summary(entity, user_id, owner_username)
        is_owner = entity["owner_id"] == user_id
        shares: list[ShareOut] = []
        if is_owner:
            shares = await self._list_shares(entity["_id"])
        usage_count = await self._survey_versions.count_documents(
            {"questions.question_ref.entity_id": entity["_id"]}
        )
        latest = next(
            (
                version
                for version in versions
                if version["_id"] == entity["latest_version_id"]
            ),
            versions[0] if versions else None,
        )
        if latest is None:  # pragma: no cover - entities always have a version
            raise QuestionNotFoundError("question has no versions")
        return QuestionDetailOut(
            **summary.model_dump(),
            latest_version=self._version_out(latest),
            versions=[self._version_out(version) for version in versions],
            shares=shares,
            usage_count=usage_count,
        )

    async def versions_by_id(
        self, version_ids: Sequence[ObjectId]
    ) -> dict[str, dict[str, Any]]:
        """Bulk lookup used by the survey service for publish validation."""

        if not version_ids:
            return {}
        cursor = self._versions.find({"_id": {"$in": list(version_ids)}})
        return {
            str(document["_id"]): document
            for document in await cursor.to_list(length=None)
        }

    # ------------------------------------------------------------------
    # questions: new versions, restore, fork
    # ------------------------------------------------------------------

    async def create_version(
        self,
        user_id: ObjectId,
        entity_id: ObjectId,
        payload: QuestionVersionIn,
    ) -> QuestionVersionOut:
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        content = payload.content
        if content.type != entity["type"]:
            raise QuestionValidationError(
                "changing the question type requires a new question (fork)"
            )

        latest = await self._versions.find_one(
            {"_id": entity["latest_version_id"]}
        )
        if latest is not None:
            content = self._inherit_option_ids(latest["content"], content)

        version = await self._insert_next_version(
            entity,
            content=content,
            parent_version_id=entity["latest_version_id"],
            created_by=user_id,
        )
        return self._version_out(version)

    def _inherit_option_ids(
        self, previous_content: dict[str, Any], content: QuestionContent
    ) -> QuestionContent:
        """Keep option ids stable across versions (invariant I6)."""

        previous_options = previous_content.get("options")
        if not previous_options or not hasattr(content, "options"):
            return content
        incoming = list(getattr(content, "options", []))
        previous = [
            Option(option_id=item["option_id"], label=item["label"])
            for item in previous_options
        ]
        merged = merge_option_ids(previous, incoming)
        return content.model_copy(update={"options": merged})

    async def _insert_next_version(
        self,
        entity: dict[str, Any],
        *,
        content: QuestionContent,
        parent_version_id: ObjectId | None,
        created_by: ObjectId,
        restored_from_version_id: ObjectId | None = None,
        attempt: int = 0,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        version_no = int(entity["latest_version_no"]) + 1
        version = {
            "_id": ObjectId(),
            "schema_version": 1,
            "entity_id": entity["_id"],
            "version_no": version_no,
            "parent_version_id": parent_version_id,
            "restored_from_version_id": restored_from_version_id,
            "content": canonical_content(content),
            "content_hash": hash_content(content),
            "created_by": created_by,
            "created_at": now,
            "legacy_key": None,
        }
        try:
            await self._versions.insert_one(version)
        except DuplicateKeyError:
            if attempt >= 2:  # pragma: no cover - retry is best effort
                raise QuestionConflictError(
                    "another version was created concurrently; retry"
                ) from None
            fresh = await self._questions.find_one({"_id": entity["_id"]})
            if fresh is None:
                raise QuestionNotFoundError("question not found") from None
            return await self._insert_next_version(
                fresh,
                content=content,
                parent_version_id=fresh["latest_version_id"],
                created_by=created_by,
                restored_from_version_id=restored_from_version_id,
                attempt=attempt + 1,
            )

        await self._questions.update_one(
            {"_id": entity["_id"]},
            {
                "$set": {
                    "latest_version_id": version["_id"],
                    "latest_version_no": version_no,
                    "version_count": version_no,
                    "title": content.title,
                    "type": content.type,
                    "updated_at": now,
                }
            },
        )
        return version

    async def restore_version(
        self,
        user_id: ObjectId,
        entity_id: ObjectId,
        version_no: int,
    ) -> QuestionVersionOut:
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        source = await self._versions.find_one(
            {"entity_id": entity_id, "version_no": version_no}
        )
        if source is None:
            raise QuestionNotFoundError("question version not found")
        content = self._parse_content(source["content"])
        version = await self._insert_next_version(
            entity,
            content=content,
            parent_version_id=entity["latest_version_id"],
            created_by=user_id,
            restored_from_version_id=source["_id"],
        )
        return self._version_out(version)

    @staticmethod
    def _parse_content(payload: dict[str, Any]) -> QuestionContent:
        from pydantic import TypeAdapter

        adapter: TypeAdapter[Any] = TypeAdapter(QuestionContent)
        return adapter.validate_python(payload)

    async def list_versions(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> list[QuestionVersionOut]:
        await self._require_entity(entity_id, user_id=user_id)
        cursor = self._versions.find({"entity_id": entity_id}).sort(
            "version_no", 1
        )
        return [
            self._version_out(document)
            for document in await cursor.to_list(length=None)
        ]

    async def fork_question(
        self,
        user_id: ObjectId,
        entity_id: ObjectId,
        payload: QuestionForkIn,
    ) -> QuestionDetailOut:
        source = await self._require_entity(
            entity_id, user_id=user_id, require_use=True
        )
        source_version = await self._versions.find_one(
            {"_id": source["latest_version_id"]}
        )
        if source_version is None:  # pragma: no cover
            raise QuestionNotFoundError("question version not found")

        if payload.content is not None:
            content = payload.content
        else:
            content = self._parse_content(source_version["content"])
            if payload.title:
                content = content.model_copy(update={"title": payload.title})
        if payload.title and payload.content is not None:
            content = content.model_copy(update={"title": payload.title})

        now = datetime.now(timezone.utc)
        new_entity_id = ObjectId()
        new_version_id = ObjectId()
        entity = {
            "_id": new_entity_id,
            "schema_version": 1,
            "owner_id": user_id,
            "root_entity_id": source.get("root_entity_id", source["_id"]),
            "source_entity_id": source["_id"],
            "source_version_id": source["latest_version_id"],
            "lineage_depth": int(source.get("lineage_depth", 0)) + 1,
            "type": content.type,
            "title": content.title,
            "visibility": QuestionVisibility.private.value,
            "latest_version_id": new_version_id,
            "latest_version_no": 1,
            "version_count": 1,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        version = {
            "_id": new_version_id,
            "schema_version": 1,
            "entity_id": new_entity_id,
            "version_no": 1,
            "parent_version_id": None,
            "restored_from_version_id": None,
            "content": canonical_content(content),
            "content_hash": hash_content(content),
            "created_by": user_id,
            "created_at": now,
            "legacy_key": None,
        }
        await self._questions.insert_one(entity)
        try:
            await self._versions.insert_one(version)
        except Exception:
            await self._questions.delete_one({"_id": new_entity_id})
            raise
        usernames = await self._usernames([user_id])
        return await self._detail(entity, user_id, usernames.get(user_id))

    # ------------------------------------------------------------------
    # questions: delete, share, usages
    # ------------------------------------------------------------------

    async def delete_question(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> None:
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        if entity.get("deleted_at") is not None:
            raise QuestionNotFoundError("question not found")
        published = await self._survey_versions.find_one(
            {
                "questions.question_ref.entity_id": entity_id,
                "state": "published",
            },
            {"_id": 1},
        )
        if published is not None:
            raise QuestionConflictError(
                "question is used by a published survey and cannot be deleted"
            )
        now = datetime.now(timezone.utc)
        await self._questions.update_one(
            {"_id": entity_id},
            {"$set": {"deleted_at": now, "updated_at": now}},
        )

    async def share_question(
        self, user_id: ObjectId, entity_id: ObjectId, payload: ShareGrantIn
    ) -> ShareOut:
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        grantee = await self._users.find_one(
            {"username": payload.grantee_username, "status": "active"},
            {"_id": 1, "username": 1},
        )
        if grantee is None:
            raise QuestionValidationError("grantee user not found")
        if grantee["_id"] == user_id:
            raise QuestionValidationError("you already own this question")

        now = datetime.now(timezone.utc)
        try:
            await self._shares.update_one(
                {"entity_id": entity_id, "grantee_id": grantee["_id"]},
                {
                    "$set": {
                        "permission": payload.permission.value,
                        "granted_by": user_id,
                    },
                    "$setOnInsert": {
                        "schema_version": 1,
                        "entity_id": entity_id,
                        "grantee_id": grantee["_id"],
                        "created_at": now,
                    },
                },
                upsert=True,
            )
        except DuplicateKeyError as exc:  # pragma: no cover - upsert wins
            raise QuestionConflictError("share already exists") from exc

        if entity.get("visibility") == QuestionVisibility.private.value:
            await self._questions.update_one(
                {"_id": entity_id},
                {"$set": {"visibility": QuestionVisibility.shared.value}},
            )
        document = await self._shares.find_one(
            {"entity_id": entity_id, "grantee_id": grantee["_id"]}
        )
        return self._share_out(document, grantee["username"])

    @staticmethod
    def _share_out(document: dict[str, Any], username: str | None) -> ShareOut:
        return ShareOut(
            entity_id=str(document["entity_id"]),
            grantee_id=str(document["grantee_id"]),
            grantee_username=username or "",
            permission=document["permission"],
            created_at=_utc(document["created_at"]),
        )

    async def _list_shares(self, entity_id: ObjectId) -> list[ShareOut]:
        cursor = self._shares.find({"entity_id": entity_id}).sort(
            "created_at", 1
        )
        documents = await cursor.to_list(length=None)
        usernames = await self._usernames(
            document["grantee_id"] for document in documents
        )
        return [
            self._share_out(document, usernames.get(document["grantee_id"]))
            for document in documents
        ]

    async def list_shares(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> list[ShareOut]:
        await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        return await self._list_shares(entity_id)

    async def revoke_share(
        self, user_id: ObjectId, entity_id: ObjectId, grantee_id: ObjectId
    ) -> None:
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )
        result = await self._shares.delete_one(
            {"entity_id": entity_id, "grantee_id": grantee_id}
        )
        if result.deleted_count == 0:
            raise QuestionNotFoundError("share not found")
        remaining = await self._shares.count_documents(
            {"entity_id": entity_id}
        )
        if (
            remaining == 0
            and entity.get("visibility") == QuestionVisibility.shared.value
        ):
            await self._questions.update_one(
                {"_id": entity_id},
                {"$set": {"visibility": QuestionVisibility.private.value}},
            )

    async def list_usages(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> list[QuestionUsageOut]:
        await self._require_entity(entity_id, user_id=user_id)
        cursor = self._survey_versions.find(
            {"questions.question_ref.entity_id": entity_id},
            {"survey_id": 1, "version_no": 1, "state": 1, "questions": 1},
        ).sort("survey_id", 1)
        versions = await cursor.to_list(length=None)
        survey_ids = {document["survey_id"] for document in versions}
        surveys: dict[ObjectId, dict[str, Any]] = {}
        if survey_ids:
            survey_cursor = self._surveys.find(
                {"_id": {"$in": list(survey_ids)}},
                {"title": 1, "status": 1},
            )
            surveys = {
                document["_id"]: document
                for document in await survey_cursor.to_list(length=None)
            }

        question_version_ids = {
            question["question_ref"]["version_id"]
            for document in versions
            for question in document.get("questions", [])
            if question.get("question_ref")
            and question["question_ref"].get("entity_id") == entity_id
        }
        numbers = {
            str(document["_id"]): document["version_no"]
            for document in (
                await self._versions.find(
                    {"_id": {"$in": list(question_version_ids)}},
                    {"version_no": 1},
                ).to_list(length=None)
            )
        }

        usages: list[QuestionUsageOut] = []
        for document in versions:
            survey = surveys.get(document["survey_id"], {})
            for question in document.get("questions", []):
                ref = question.get("question_ref")
                if not ref or ref.get("entity_id") != entity_id:
                    continue
                usages.append(
                    QuestionUsageOut(
                        survey_id=str(document["survey_id"]),
                        survey_title=survey.get("title", ""),
                        survey_status=survey.get("status", "unknown"),
                        survey_version_id=str(document["_id"]),
                        survey_version_no=document["version_no"],
                        instance_question_id=question["question_id"],
                        question_version_id=str(ref["version_id"]),
                        question_version_no=numbers.get(
                            str(ref["version_id"]), 0
                        ),
                        is_published=document.get("state") == "published",
                    )
                )
        usages.sort(
            key=lambda item: (
                item.survey_title,
                item.survey_version_no,
                item.instance_question_id,
            )
        )
        return usages

    # ------------------------------------------------------------------
    # question banks
    # ------------------------------------------------------------------

    async def create_library(
        self, owner_id: ObjectId, payload: LibraryCreateIn
    ) -> LibraryOut:
        now = datetime.now(timezone.utc)
        document = {
            "_id": ObjectId(),
            "schema_version": 1,
            "owner_id": owner_id,
            "name": payload.name,
            "description": payload.description,
            "visibility": payload.visibility.value,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self._libraries.insert_one(document)
        except DuplicateKeyError as exc:
            raise QuestionConflictError(
                "a library with this name already exists"
            ) from exc
        return await self._library_out(document, owner_id)

    async def _library_out(
        self, document: dict[str, Any], user_id: ObjectId
    ) -> LibraryOut:
        usernames = await self._usernames([document["owner_id"]])
        item_count = await self._items.count_documents(
            {"library_id": document["_id"]}
        )
        return LibraryOut(
            id=str(document["_id"]),
            owner_id=str(document["owner_id"]),
            owner_username=usernames.get(document["owner_id"]),
            name=document["name"],
            description=document.get("description", ""),
            visibility=document.get("visibility", "private"),
            item_count=item_count,
            created_at=_utc(document["created_at"]),
            updated_at=_utc(document["updated_at"]),
            is_owner=document["owner_id"] == user_id,
        )

    async def list_libraries(
        self, user_id: ObjectId, *, include_public: bool = True
    ) -> list[LibraryOut]:
        query: dict[str, Any] = {"owner_id": user_id}
        if include_public:
            query = {
                "$or": [
                    {"owner_id": user_id},
                    {"visibility": LibraryVisibility.public.value},
                ]
            }
        cursor = self._libraries.find(query).sort("updated_at", -1).limit(
            MAX_LIST
        )
        documents = await cursor.to_list(length=None)
        return [
            await self._library_out(document, user_id)
            for document in documents
        ]

    async def _require_library(
        self, library_id: ObjectId, *, user_id: ObjectId, require_owner: bool
    ) -> dict[str, Any]:
        library = await self._libraries.find_one({"_id": library_id})
        if library is None:
            raise QuestionNotFoundError("library not found")
        if require_owner:
            if library["owner_id"] != user_id:
                raise QuestionNotFoundError("library not found")
        elif (
            library["owner_id"] != user_id
            and library.get("visibility") != LibraryVisibility.public.value
        ):
            raise QuestionNotFoundError("library not found")
        return library

    async def get_library(
        self, user_id: ObjectId, library_id: ObjectId
    ) -> LibraryDetailOut:
        library = await self._require_library(
            library_id, user_id=user_id, require_owner=False
        )
        base = await self._library_out(library, user_id)
        cursor = self._items.find({"library_id": library_id}).sort(
            "added_at", -1
        )
        items = await cursor.to_list(length=None)
        entity_ids = [item["entity_id"] for item in items]
        entities: dict[ObjectId, dict[str, Any]] = {}
        if entity_ids:
            entity_cursor = self._questions.find(
                {"_id": {"$in": entity_ids}}, {"title": 1, "type": 1}
            )
            entities = {
                document["_id"]: document
                for document in await entity_cursor.to_list(length=None)
            }
        rows: list[LibraryItemOut] = []
        for item in items:
            entity = entities.get(item["entity_id"])
            if entity is None or entity.get("deleted_at") is not None:
                continue
            rows.append(
                LibraryItemOut(
                    entity_id=str(item["entity_id"]),
                    title=entity["title"],
                    type=entity["type"],
                    note=item.get("note"),
                    tags=item.get("tags", []),
                    latest_version_id=str(entity.get("latest_version_id", "")),
                    latest_version_no=int(entity.get("latest_version_no", 1)),
                    added_at=_utc(item["added_at"]),
                )
            )
        return LibraryDetailOut(**base.model_dump(), items=rows)

    async def update_library(
        self,
        user_id: ObjectId,
        library_id: ObjectId,
        payload: LibraryUpdateIn,
    ) -> LibraryOut:
        library = await self._require_library(
            library_id, user_id=user_id, require_owner=True
        )
        changes = payload.model_dump(exclude_unset=True, mode="json")
        if changes:
            changes["updated_at"] = datetime.now(timezone.utc)
            try:
                await self._libraries.update_one(
                    {"_id": library_id}, {"$set": changes}
                )
            except DuplicateKeyError as exc:
                raise QuestionConflictError(
                    "a library with this name already exists"
                ) from exc
            library = await self._libraries.find_one({"_id": library_id})
        return await self._library_out(library, user_id)

    async def delete_library(
        self, user_id: ObjectId, library_id: ObjectId
    ) -> None:
        await self._require_library(
            library_id, user_id=user_id, require_owner=True
        )
        await self._items.delete_many({"library_id": library_id})
        await self._libraries.delete_one({"_id": library_id})

    async def add_library_item(
        self,
        user_id: ObjectId,
        library_id: ObjectId,
        payload: LibraryItemIn,
    ) -> LibraryItemOut:
        await self._require_library(
            library_id, user_id=user_id, require_owner=True
        )
        entity_id = ObjectId(payload.entity_id)
        entity = await self._require_entity(
            entity_id, user_id=user_id, require_use=True
        )
        now = datetime.now(timezone.utc)
        document = {
            "_id": ObjectId(),
            "schema_version": 1,
            "library_id": library_id,
            "entity_id": entity_id,
            "added_by": user_id,
            "added_at": now,
            "note": payload.note,
            "tags": payload.tags,
        }
        try:
            await self._items.insert_one(document)
        except DuplicateKeyError:
            existing = await self._items.find_one(
                {"library_id": library_id, "entity_id": entity_id}
            )
            if existing is not None:
                return LibraryItemOut(
                    entity_id=str(entity_id),
                    title=entity["title"],
                    type=entity["type"],
                    note=existing.get("note"),
                    tags=existing.get("tags", []),
                    latest_version_id=str(entity["latest_version_id"]),
                    latest_version_no=int(entity["latest_version_no"]),
                    added_at=_utc(existing["added_at"]),
                )
            raise QuestionConflictError("item already exists") from None
        await self._libraries.update_one(
            {"_id": library_id}, {"$set": {"updated_at": now}}
        )
        return LibraryItemOut(
            entity_id=str(entity_id),
            title=entity["title"],
            type=entity["type"],
            note=payload.note,
            tags=payload.tags,
            latest_version_id=str(entity["latest_version_id"]),
            latest_version_no=int(entity["latest_version_no"]),
            added_at=now,
        )

    async def remove_library_item(
        self, user_id: ObjectId, library_id: ObjectId, entity_id: ObjectId
    ) -> None:
        await self._require_library(
            library_id, user_id=user_id, require_owner=True
        )
        result = await self._items.delete_one(
            {"library_id": library_id, "entity_id": entity_id}
        )
        if result.deleted_count == 0:
            raise QuestionNotFoundError("library item not found")
        await self._libraries.update_one(
            {"_id": library_id},
            {"$set": {"updated_at": datetime.now(timezone.utc)}},
        )

    # ------------------------------------------------------------------
    # helpers used by the survey service
    # ------------------------------------------------------------------

    async def resolve_version_for_use(
        self, user_id: ObjectId, version_id: ObjectId
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load a question version the user is allowed to insert."""

        version = await self._versions.find_one({"_id": version_id})
        if version is None:
            raise QuestionNotFoundError("question version not found")
        entity = await self._require_entity(
            version["entity_id"], user_id=user_id, require_use=True
        )
        return entity, version

    async def ensure_owner_entity(
        self, user_id: ObjectId, entity_id: ObjectId
    ) -> dict[str, Any]:
        return await self._require_entity(
            entity_id, user_id=user_id, require_owner=True
        )

    async def replace_latest_pointer(
        self, entity_id: ObjectId, version_id: ObjectId
    ) -> None:  # pragma: no cover - reserved for repair tooling
        await self._questions.update_one(
            {"_id": entity_id},
            {"$set": {"latest_version_id": version_id}},
        )


__all__ = [
    "MAX_LIST",
    "QuestionConflictError",
    "QuestionLibraryService",
    "QuestionNotFoundError",
    "QuestionValidationError",
    "SCOPES",
    "SCOPE_LIBRARY",
    "SCOPE_MINE",
    "SCOPE_PUBLIC",
    "SCOPE_SHARED",
    "SCOPE_USABLE",
]
