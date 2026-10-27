"""Verify the phase-2 migration left the database consistent.

Checks the invariants documented in ``docs/第二阶段/数据模型变更说明.md``:

* I1 every ``question_versions`` document is self-consistent (hash matches);
* I2 the embedded snapshot of a referenced question equals the library content;
* I4 every stored answer still points at the version its survey pinned;
* referential integrity: no dangling ``question_ref``;
* entity counters (``version_count``, ``latest_version_id``) match reality.

Usage::

    python scripts/verify_migration.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bson import ObjectId
from pydantic import TypeAdapter
from pymongo.asynchronous.database import AsyncDatabase

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas.pydantic import QuestionContent, content_of, hash_content  # noqa: E402
from schemas.pydantic.models import Question  # noqa: E402

CONTENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(QuestionContent)
QUESTION_ADAPTER: TypeAdapter[Any] = TypeAdapter(Question)


@dataclass
class VerifyReport:
    checks: int = 0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def lines(self) -> list[str]:
        rows = [f"{name:28s}: {value}" for name, value in self.counts.items()]
        rows.append(f"{'assertions checked':28s}: {self.checks}")
        rows.append(f"{'failures':28s}: {len(self.failures)}")
        rows.append(f"{'warnings':28s}: {len(self.warnings)}")
        for failure in self.failures[:30]:
            rows.append(f"  FAIL {failure}")
        for warning in self.warnings[:15]:
            rows.append(f"  WARN {warning}")
        return rows


async def verify(db: AsyncDatabase) -> VerifyReport:
    report = VerifyReport()

    for name in (
        "users",
        "surveys",
        "survey_versions",
        "responses",
        "questions",
        "question_versions",
        "question_shares",
        "question_libraries",
        "question_library_items",
    ):
        report.counts[name] = await db[name].count_documents({})

    # ---- 1. question_versions are self-consistent ----------------------
    version_cache: dict[ObjectId, dict[str, Any]] = {}
    entity_versions: dict[ObjectId, list[dict[str, Any]]] = {}

    async for version in db["question_versions"].find({}):
        report.checks += 1
        version_cache[version["_id"]] = version
        entity_versions.setdefault(version["entity_id"], []).append(version)
        try:
            content = CONTENT_ADAPTER.validate_python(version["content"])
        except Exception as exc:  # noqa: BLE001 - report, do not raise
            report.fail(f"question_version {version['_id']}: invalid content ({exc})")
            continue
        if hash_content(content) != version.get("content_hash"):
            report.fail(
                f"question_version {version['_id']}: content_hash mismatch"
            )

    # ---- 2. entity counters -------------------------------------------
    async for entity in db["questions"].find({}):
        report.checks += 1
        versions = entity_versions.get(entity["_id"], [])
        if not versions:
            report.fail(f"question {entity['_id']}: has no versions")
            continue
        if entity.get("version_count") != len(versions):
            report.fail(
                f"question {entity['_id']}: version_count "
                f"{entity.get('version_count')} != {len(versions)}"
            )
        newest = max(versions, key=lambda item: item["version_no"])
        if entity.get("latest_version_id") != newest["_id"]:
            report.fail(f"question {entity['_id']}: latest_version_id is stale")
        if entity.get("latest_version_no") != newest["version_no"]:
            report.fail(
                f"question {entity['_id']}: latest_version_no is stale"
            )
        if entity.get("root_entity_id") is None:
            report.fail(f"question {entity['_id']}: missing root_entity_id")

    # ---- 3. embedded snapshots match the referenced version -----------
    response_mappings: dict[ObjectId, dict[str, dict[str, Any]]] = {}
    survey_version_ids: set[ObjectId] = set()
    async for version in db["survey_versions"].find({}):
        survey_version_ids.add(version["_id"])
        mapping: dict[str, dict[str, Any]] = {}
        for question in version.get("questions") or []:
            ref = question.get("question_ref")
            if not ref:
                continue
            report.checks += 1
            mapping[question["question_id"]] = ref
            stored = version_cache.get(ref.get("version_id"))
            if stored is None:
                report.fail(
                    f"survey_version {version['_id']}/{question['question_id']}: "
                    "dangling version_id"
                )
                continue
            if stored.get("entity_id") != ref.get("entity_id"):
                report.fail(
                    f"survey_version {version['_id']}/{question['question_id']}: "
                    "entity_id does not match the referenced version"
                )
            try:
                parsed = QUESTION_ADAPTER.validate_python(question)
                snapshot_hash = hash_content(content_of(parsed))
            except Exception as exc:  # noqa: BLE001
                report.fail(
                    f"survey_version {version['_id']}/{question['question_id']}: "
                    f"invalid embedded question ({exc})"
                )
                continue
            if snapshot_hash != stored.get("content_hash"):
                report.fail(
                    f"survey_version {version['_id']}/{question['question_id']}: "
                    "snapshot content differs from the referenced version"
                )
        if mapping:
            response_mappings[version["_id"]] = mapping

    # ---- 4. answers still point at the pinned version ------------------
    async for response in db["responses"].find({}):
        mapping = response_mappings.get(response["survey_version_id"])
        for answer in response.get("answers") or []:
            report.checks += 1
            ref = answer.get("question_ref")
            if ref is None:
                if mapping and answer.get("question_id") in mapping:
                    report.warn(
                        f"response {response['_id']}: answer "
                        f"{answer.get('question_id')} has no question_ref"
                    )
                continue
            if response["survey_version_id"] not in survey_version_ids:
                report.fail(
                    f"response {response['_id']}: unknown survey_version_id"
                )
                continue
            if version_cache.get(ref.get("version_id")) is None:
                report.fail(
                    f"response {response['_id']}: dangling version_id in answer "
                    f"{answer.get('question_id')}"
                )
                continue
            expected = (mapping or {}).get(answer.get("question_id"))
            if expected is not None and expected != ref:
                report.fail(
                    f"response {response['_id']}: answer "
                    f"{answer.get('question_id')} points at a different version"
                )
            elif expected is None:
                report.warn(
                    f"response {response['_id']}: answer "
                    f"{answer.get('question_id')} references a question that is "
                    "not part of its survey version"
                )

    # ---- 5. library items and shares reference live questions ---------
    for collection, label in (
        ("question_library_items", "item"),
        ("question_shares", "share"),
        ("question_versions", "version"),
    ):
        async for document in db[collection].find({}):
            report.checks += 1
            if await db["questions"].find_one(
                {"_id": document["entity_id"]}, {"_id": 1}
            ) is None:
                report.fail(
                    f"{label} {document['_id']}: dangling entity_id"
                )

    return report


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    from pymongo.asynchronous.mongo_client import AsyncMongoClient

    from backend.config import get_settings

    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    try:
        db = client[settings.mongodb_db]
        print(f"database: {settings.mongodb_db}")
        report = await verify(db)
        for line in report.lines():
            print(line)
        if report.failures:
            print("\nMIGRATION VERIFICATION FAILED")
            return 1
        print("\nMIGRATION VERIFICATION PASSED")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
