"""Phase 2 migration: give every embedded question a shared-library identity.

Phase 1 stored questions inline inside ``survey_versions.questions[]`` with no
cross-survey identity. Phase 2 adds ``questions`` / ``question_versions`` and
points each embedded question at them through ``question_ref``.

The migration is **additive and idempotent**:

* it never deletes or reorders an embedded question;
* the idempotency key is ``legacy_key = "{survey_version_id}:{question_id}"``,
  stored on ``question_versions`` under a unique partial index;
* running it twice reports ``created=0`` and only rewrites documents whose
  reference is still missing.

Phase 1 had no sharing, so every ``(survey version, question)`` pair becomes its
own entity. Merging equal-looking questions would require guessing intent, so
the migration deliberately does not do it.

Usage::

    python scripts/migrate_phase2.py            # apply
    python scripts/migrate_phase2.py --dry-run  # report only

Environment: ``MONGODB_URI`` / ``MONGODB_DB`` (same variables as the app).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pydantic import TypeAdapter, ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import BulkWriteError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas.pydantic import content_of, hash_content  # noqa: E402
from schemas.pydantic.models import Question  # noqa: E402

QUESTION_ADAPTER: TypeAdapter[Any] = TypeAdapter(Question)


def legacy_key(survey_version_id: Any, question_id: str) -> str:
    return f"{survey_version_id}:{question_id}"


@dataclass
class MigrationReport:
    versions_scanned: int = 0
    questions_seen: int = 0
    already_migrated: int = 0
    created: int = 0
    reused: int = 0
    skipped: int = 0
    refs_written: int = 0
    skipped_detail: list[str] = field(default_factory=list)
    dry_run: bool = False

    def lines(self) -> list[str]:
        prefix = "[dry-run] " if self.dry_run else ""
        rows = [
            f"{prefix}survey_versions scanned : {self.versions_scanned}",
            f"{prefix}embedded questions seen: {self.questions_seen}",
            f"{prefix}already had a ref      : {self.already_migrated}",
            f"{prefix}entities created       : {self.created}",
            f"{prefix}reused (partial rerun) : {self.reused}",
            f"{prefix}skipped (unparsable)   : {self.skipped}",
            f"{prefix}refs written           : {self.refs_written}",
        ]
        for detail in self.skipped_detail[:20]:
            rows.append(f"{prefix}  skipped: {detail}")
        return rows


def _build_entity(
    *,
    owner_id: Any,
    entity_id: ObjectId,
    version_id: ObjectId,
    content: Any,
    now: datetime,
) -> dict[str, Any]:
    return {
        "_id": entity_id,
        "schema_version": 1,
        "owner_id": owner_id,
        "root_entity_id": entity_id,
        "source_entity_id": None,
        "source_version_id": None,
        "lineage_depth": 0,
        "type": content.type,
        "title": content.title,
        "visibility": "private",
        "latest_version_id": version_id,
        "latest_version_no": 1,
        "version_count": 1,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _build_version(
    *,
    entity_id: ObjectId,
    version_id: ObjectId,
    content: Any,
    created_by: Any,
    now: datetime,
    key: str,
) -> dict[str, Any]:
    payload = content.model_dump(mode="json", exclude_none=True)
    return {
        "_id": version_id,
        "schema_version": 1,
        "entity_id": entity_id,
        "version_no": 1,
        "parent_version_id": None,
        "restored_from_version_id": None,
        "content": payload,
        "content_hash": hash_content(content),
        "created_by": created_by,
        "created_at": now,
        "legacy_key": key,
    }


async def migrate(
    db: AsyncDatabase, *, dry_run: bool = False
) -> MigrationReport:
    """Add ``question_ref`` to every embedded question that can be parsed."""

    report = MigrationReport(dry_run=dry_run)
    versions = db["survey_versions"]
    question_versions = db["question_versions"]
    questions = db["questions"]

    now = datetime.now(timezone.utc)
    async for version in versions.find({}).sort("_id", 1):
        report.versions_scanned += 1
        embedded = version.get("questions") or []
        if not embedded:
            continue
        report.questions_seen += len(embedded)

        survey_version_id = version["_id"]
        owner_id = version.get("created_by")
        keys = [
            legacy_key(survey_version_id, item["question_id"])
            for item in embedded
            if item.get("question_id")
        ]
        existing: dict[str, dict[str, Any]] = {}
        if keys:
            cursor = question_versions.find(
                {"legacy_key": {"$in": keys}},
                {"entity_id": 1, "legacy_key": 1},
            )
            for document in await cursor.to_list(length=None):
                existing[document["legacy_key"]] = document

        updated_questions: list[dict[str, Any]] = []
        new_entities: list[dict[str, Any]] = []
        new_versions: list[dict[str, Any]] = []

        for item in embedded:
            if item.get("question_ref"):
                report.already_migrated += 1
                updated_questions.append(item)
                continue

            question_id = item.get("question_id")
            try:
                parsed = QUESTION_ADAPTER.validate_python(item)
                content = content_of(parsed)
            except ValidationError as exc:
                report.skipped += 1
                report.skipped_detail.append(
                    f"{survey_version_id}/{question_id}: {exc.errors()[:1]}"
                )
                updated_questions.append(item)
                continue

            key = legacy_key(survey_version_id, question_id)
            if key in existing:
                ref = {
                    "entity_id": existing[key]["entity_id"],
                    "version_id": existing[key]["_id"],
                }
                report.reused += 1
            else:
                entity_id = ObjectId()
                version_id = ObjectId()
                new_entities.append(
                    _build_entity(
                        owner_id=owner_id,
                        entity_id=entity_id,
                        version_id=version_id,
                        content=content,
                        now=now,
                    )
                )
                new_versions.append(
                    _build_version(
                        entity_id=entity_id,
                        version_id=version_id,
                        content=content,
                        created_by=owner_id,
                        now=now,
                        key=key,
                    )
                )
                ref = {"entity_id": entity_id, "version_id": version_id}
                report.created += 1

            report.refs_written += 1
            updated_questions.append({**item, "question_ref": ref})

        if dry_run:
            continue

        if new_entities:
            await _insert_ignore_duplicates(questions, new_entities)
            await _insert_ignore_duplicates(question_versions, new_versions)

        if report.refs_written and len(updated_questions) == len(embedded):
            await versions.update_one(
                {"_id": survey_version_id},
                {"$set": {"questions": updated_questions}},
            )

    return report


async def _insert_ignore_duplicates(
    collection: Any, documents: list[dict[str, Any]]
) -> None:
    if not documents:
        return
    try:
        await collection.insert_many(documents, ordered=False)
    except BulkWriteError as exc:
        write_errors = exc.details.get("writeErrors", [])
        unexpected = [
            error for error in write_errors if error.get("code") != 11000
        ]
        if unexpected:
            raise


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    args = parser.parse_args(argv)

    from pymongo.asynchronous.mongo_client import AsyncMongoClient

    from backend.config import get_settings

    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    try:
        db = client[settings.mongodb_db]
        print(f"database: {settings.mongodb_db}")
        report = await migrate(db, dry_run=args.dry_run)
        for line in report.lines():
            print(line)
        if report.skipped:
            print(
                "\nWARNING: some questions could not be parsed; their embedded "
                "content was left untouched."
            )
        print("\nmigration completed")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
