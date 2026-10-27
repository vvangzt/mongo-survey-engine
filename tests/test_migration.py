"""Phase-2 migration tests.

The claim under test: phase-1 data can gain a shared-library identity **without
changing a single byte of its embedded content**, and the migration can be run
twice with the same result.

These tests talk to MongoDB directly (no HTTP) so they cover the scripts in
``scripts/`` the way an operator would run them.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId
from pymongo import MongoClient
from pymongo.asynchronous.mongo_client import AsyncMongoClient

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import backfill_response_refs  # noqa: E402
import migrate_phase2  # noqa: E402
import verify_migration  # noqa: E402
from schemas.pydantic import content_of, hash_content  # noqa: E402
from schemas.pydantic.models import Question  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

QUESTION_ADAPTER: TypeAdapter[Any] = TypeAdapter(Question)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)

QUESTIONS = [
    {
        "question_id": "q_single_0001",
        "type": "single_choice",
        "title": "你的身份是？",
        "required": True,
        "options": [
            {"option_id": "o_student_0001", "label": "学生"},
            {"option_id": "o_teacher_0001", "label": "教师"},
        ],
        "logic": {"fallback": {"action": "next"}, "rules": []},
    },
    {
        "question_id": "q_number_0002",
        "type": "number",
        "title": "年龄（周岁）",
        "required": False,
        "validation": {"integer": True, "min": 0, "max": 120},
    },
    {
        "question_id": "q_text_0003",
        "type": "text",
        "title": "补充建议",
        "required": False,
        "validation": {"min_length": 0, "max_length": 200, "trim": True},
    },
]

ANSWERS = [
    {
        "question_id": "q_single_0001",
        "type": "single_choice",
        "option_ids": ["o_student_0001"],
    },
    {
        "question_id": "q_number_0002",
        "type": "number",
        "number": 21,
    },
]


def seed_phase1_data(db: Any) -> dict[str, Any]:
    """Insert documents shaped exactly like phase 1 produced them."""

    user_id = ObjectId()
    survey_id = ObjectId()
    version_id = ObjectId()
    draft_id = ObjectId()

    db["users"].insert_one(
        {
            "_id": user_id,
            "schema_version": 1,
            "username": f"legacy_{uuid.uuid4().hex[:8]}",
            "email": f"legacy_{uuid.uuid4().hex[:8]}@example.com",
            "password_hash": "x" * 40,
            "display_name": "旧用户",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    db["surveys"].insert_one(
        {
            "_id": survey_id,
            "schema_version": 1,
            "owner_id": user_id,
            "slug": f"s-{uuid.uuid4().hex[:12]}",
            "title": "第一阶段问卷",
            "description": "",
            "status": "published",
            "allow_anonymous": True,
            "allow_multiple_responses": True,
            "opens_at": NOW,
            "closes_at": None,
            "current_draft_version_id": draft_id,
            "published_version_id": version_id,
            "last_version_no": 2,
            "published_at": NOW,
            "closed_at": None,
            "deleted_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    db["survey_versions"].insert_many(
        [
            {
                "_id": version_id,
                "schema_version": 1,
                "survey_id": survey_id,
                "version_no": 1,
                "state": "published",
                "content_schema_version": 1,
                "revision": 2,
                "questions": QUESTIONS,
                "created_by": user_id,
                "created_at": NOW,
                "updated_at": NOW,
                "published_at": NOW,
                "content_hash": None,
            },
            {
                "_id": draft_id,
                "schema_version": 1,
                "survey_id": survey_id,
                "version_no": 2,
                "state": "draft",
                "content_schema_version": 1,
                "revision": 1,
                "questions": QUESTIONS,
                "created_by": user_id,
                "created_at": NOW,
                "updated_at": NOW,
                "published_at": None,
                "content_hash": None,
            },
        ]
    )
    db["responses"].insert_many(
        [
            {
                "_id": ObjectId(),
                "schema_version": 1,
                "survey_id": survey_id,
                "survey_version_id": version_id,
                "respondent_id": None,
                "is_anonymous": True,
                "submission_token": f"tok{uuid.uuid4().hex[:20]}",
                "answers": ANSWERS,
                "submitted_at": NOW,
            },
            {
                "_id": ObjectId(),
                "schema_version": 1,
                "survey_id": survey_id,
                "survey_version_id": draft_id,
                "respondent_id": None,
                "is_anonymous": True,
                "submission_token": f"tok{uuid.uuid4().hex[:20]}",
                "answers": [ANSWERS[0]],
                "submitted_at": NOW,
            },
        ]
    )
    return {
        "user_id": user_id,
        "survey_id": survey_id,
        "version_id": version_id,
        "draft_id": draft_id,
    }


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _with_db(uri: str, name: str, action: Any) -> Any:
    client = AsyncMongoClient(uri, tz_aware=True)
    try:
        return await action(client[name])
    finally:
        await client.close()


@pytest.fixture
def legacy_db(mongo_uri: str):
    name = f"migration_{uuid.uuid4().hex[:8]}"
    client = MongoClient(mongo_uri)
    seeded = seed_phase1_data(client[name])
    try:
        yield mongo_uri, name, seeded
    finally:
        client.drop_database(name)
        client.close()


def _snapshot(uri: str, db_name: str) -> dict[str, Any]:
    client = MongoClient(uri)
    try:
        db = client[db_name]
        return {
            "survey_versions": list(
                db["survey_versions"].find({}).sort("_id", 1)
            ),
            "responses": list(db["responses"].find({}).sort("_id", 1)),
        }
    finally:
        client.close()


def test_migration_adds_references_without_touching_content(legacy_db) -> None:
    uri, name, seeded = legacy_db
    before = _snapshot(uri, name)

    report = _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))

    # Two versions x three questions, each pair becomes its own entity because
    # phase 1 had no sharing at all.
    assert report.versions_scanned == 2
    assert report.questions_seen == 6
    assert report.created == 6
    assert report.refs_written == 6
    assert report.skipped == 0

    client = MongoClient(uri)
    try:
        db = client[name]
        assert db["questions"].count_documents({}) == 6
        assert db["question_versions"].count_documents({}) == 6

        # Every embedded question kept its id, order, type and options.
        for before_version, after_version in zip(
            before["survey_versions"],
            list(db["survey_versions"].find({}).sort("_id", 1)),
        ):
            assert len(after_version["questions"]) == len(
                before_version["questions"]
            )
            for before_question, after_question in zip(
                before_version["questions"], after_version["questions"]
            ):
                assert after_question["question_id"] == before_question["question_id"]
                ref = after_question["question_ref"]
                assert ref["entity_id"] and ref["version_id"]
                stripped = {
                    key: value
                    for key, value in after_question.items()
                    if key != "question_ref"
                }
                assert stripped == before_question

        # The stored content hash equals the hash of the embedded snapshot.
        for document in db["question_versions"].find({}):
            parsed = QUESTION_ADAPTER.validate_python(
                next(
                    question
                    for version in before["survey_versions"]
                    for question in version["questions"]
                    if question["question_id"]
                    == str(document["legacy_key"]).split(":", 1)[1]
                )
            )
            assert hash_content(content_of(parsed)) == document["content_hash"]
    finally:
        client.close()


def test_migration_is_idempotent(legacy_db) -> None:
    uri, name, _seeded = legacy_db

    first = _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))
    second = _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))

    assert first.created == 6
    assert second.created == 0
    assert second.already_migrated == 6
    assert second.refs_written == 0

    client = MongoClient(uri)
    try:
        db = client[name]
        assert db["questions"].count_documents({}) == 6
        assert db["question_versions"].count_documents({}) == 6
    finally:
        client.close()


def test_dry_run_writes_nothing(legacy_db) -> None:
    uri, name, _seeded = legacy_db

    report = _run(
        _with_db(uri, name, lambda db: migrate_phase2.migrate(db, dry_run=True))
    )
    assert report.created == 6

    client = MongoClient(uri)
    try:
        db = client[name]
        assert db["questions"].count_documents({}) == 0
        assert db["question_versions"].count_documents({}) == 0
        for version in db["survey_versions"].find({}):
            for question in version["questions"]:
                assert "question_ref" not in question
    finally:
        client.close()


def test_backfill_and_verification(legacy_db) -> None:
    uri, name, seeded = legacy_db

    _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))
    report = _run(
        _with_db(uri, name, lambda db: backfill_response_refs.backfill(db))
    )

    assert report.versions_scanned == 2
    assert report.responses_scanned == 2
    assert report.responses_updated == 2
    assert report.answers_updated == 3
    assert report.answers_unmapped == 0

    check = _run(_with_db(uri, name, verify_migration.verify))
    assert check.failures == [], check.failures

    client = MongoClient(uri)
    try:
        db = client[name]
        mappings = {
            version["_id"]: {
                question["question_id"]: question["question_ref"]
                for question in version["questions"]
            }
            for version in db["survey_versions"].find({})
        }
        for response in db["responses"].find({}):
            mapping = mappings[response["survey_version_id"]]
            for answer in response["answers"]:
                assert answer["question_ref"] == mapping[answer["question_id"]]
    finally:
        client.close()


def test_verification_detects_a_tampered_snapshot(legacy_db) -> None:
    uri, name, seeded = legacy_db

    _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))

    client = MongoClient(uri)
    try:
        db = client[name]
        db["survey_versions"].update_one(
            {"_id": seeded["version_id"], "questions.question_id": "q_text_0003"},
            {
                "$set": {
                    "questions.$.title": "被篡改的标题",
                }
            },
        )
    finally:
        client.close()

    check = _run(_with_db(uri, name, verify_migration.verify))
    assert any(
        "snapshot content differs" in failure for failure in check.failures
    ), check.failures


def test_unparsable_question_is_skipped_not_deleted(legacy_db) -> None:
    uri, name, seeded = legacy_db

    client = MongoClient(uri)
    try:
        client[name]["survey_versions"].update_one(
            {"_id": seeded["version_id"], "questions.question_id": "q_number_0002"},
            {"$set": {"questions.$.options": []}},
        )
    finally:
        client.close()

    report = _run(_with_db(uri, name, lambda db: migrate_phase2.migrate(db)))

    assert report.skipped == 1
    assert report.created == 5

    client = MongoClient(uri)
    try:
        version = client[name]["survey_versions"].find_one(
            {"_id": seeded["version_id"]}
        )
        broken = next(
            question
            for question in version["questions"]
            if question["question_id"] == "q_number_0002"
        )
        # Untouched: the migration must never drop data it cannot interpret.
        assert "question_ref" not in broken
        assert broken["options"] == []
    finally:
        client.close()
