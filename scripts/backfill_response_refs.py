"""Backfill ``responses.answers[].question_ref`` after the phase-2 migration.

Answers written in phase 1 only carry the survey-version-local ``question_id``.
Cross-survey statistics need the stable library identity, so this script copies
the reference from the survey version that the response answered.

It is additive and idempotent: answers that already carry a reference are left
alone, and the script never rewrites a response that needs no change.

Usage::

    python scripts/backfill_response_refs.py
    python scripts/backfill_response_refs.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class BackfillReport:
    versions_scanned: int = 0
    versions_with_refs: int = 0
    responses_scanned: int = 0
    responses_updated: int = 0
    answers_updated: int = 0
    answers_unmapped: int = 0
    dry_run: bool = False

    def lines(self) -> list[str]:
        prefix = "[dry-run] " if self.dry_run else ""
        return [
            f"{prefix}survey_versions scanned : {self.versions_scanned}",
            f"{prefix}versions with refs      : {self.versions_with_refs}",
            f"{prefix}responses scanned       : {self.responses_scanned}",
            f"{prefix}responses updated       : {self.responses_updated}",
            f"{prefix}answers updated         : {self.answers_updated}",
            f"{prefix}answers without mapping : {self.answers_unmapped}",
        ]


def reference_map(version: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for question in version.get("questions") or []:
        ref = question.get("question_ref")
        if ref and question.get("question_id"):
            mapping[question["question_id"]] = ref
    return mapping


async def backfill(
    db: AsyncDatabase, *, batch_size: int = 500, dry_run: bool = False
) -> BackfillReport:
    report = BackfillReport(dry_run=dry_run)
    versions = db["survey_versions"]
    responses = db["responses"]

    async for version in versions.find(
        {"questions.question_ref": {"$exists": True}}
    ).sort("_id", 1):
        report.versions_scanned += 1
        mapping = reference_map(version)
        if not mapping:
            continue
        report.versions_with_refs += 1

        operations: list[UpdateOne] = []
        async for response in responses.find(
            {"survey_version_id": version["_id"]}
        ):
            report.responses_scanned += 1
            changed = False
            answers: list[dict[str, Any]] = []
            for answer in response.get("answers") or []:
                if answer.get("question_ref"):
                    answers.append(answer)
                    continue
                ref = mapping.get(answer.get("question_id", ""))
                if ref is None:
                    report.answers_unmapped += 1
                    answers.append(answer)
                    continue
                answers.append({**answer, "question_ref": ref})
                changed = True
                report.answers_updated += 1
            if not changed:
                continue
            report.responses_updated += 1
            operations.append(
                UpdateOne(
                    {"_id": response["_id"], "answers.question_ref": {"$exists": False}},
                    {"$set": {"answers": answers}},
                )
            )
            if len(operations) >= batch_size:
                if not dry_run:
                    await responses.bulk_write(operations, ordered=False)
                operations = []

        if operations and not dry_run:
            await responses.bulk_write(operations, ordered=False)

    return report


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from pymongo.asynchronous.mongo_client import AsyncMongoClient

    from backend.config import get_settings

    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    try:
        db = client[settings.mongodb_db]
        print(f"database: {settings.mongodb_db}")
        report = await backfill(db, dry_run=args.dry_run)
        for line in report.lines():
            print(line)
        print("\nbackfill completed")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
