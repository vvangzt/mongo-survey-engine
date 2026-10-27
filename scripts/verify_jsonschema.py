"""Validate the example documents against the canonical JSON Schemas.

This is a development-time check. Production services should validate writes
with their native models (Pydantic/Mongoose) and keep MongoDB validators as a
second line of defence.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "json-schema"
EXAMPLE_DIR = ROOT / "examples"

EXAMPLE_TO_SCHEMA = {
    "users.example.json": "users.schema.json",
    "surveys.example.json": "surveys.schema.json",
    "survey_versions.example.json": "survey_versions.schema.json",
    "responses.anonymous.example.json": "responses.schema.json",
    "responses.identified-short-path.example.json": "responses.schema.json",
    "survey_stat_snapshots.example.json": "survey_stat_snapshots.schema.json",
    "questions.example.json": "questions.schema.json",
    "question_versions.example.json": "question_versions.schema.json",
    "question_shares.example.json": "question_shares.schema.json",
    "question_libraries.example.json": "question_libraries.schema.json",
    "question_library_items.example.json": "question_library_items.schema.json",
    "survey_versions.with_library_refs.example.json": "survey_versions.schema.json",
    "responses.with_library_refs.example.json": "responses.schema.json",
}


def load_schemas() -> tuple[dict[str, dict], Registry]:
    schemas: dict[str, dict] = {}
    registry = Registry()
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if path.name != "common.schema.json":
            Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
        schemas[path.name] = schema
    return schemas, registry


def main() -> int:
    schemas, registry = load_schemas()
    failures = 0
    for example_name, schema_name in EXAMPLE_TO_SCHEMA.items():
        example = json.loads(
            (EXAMPLE_DIR / example_name).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schemas[schema_name], registry=registry)
        errors = sorted(
            validator.iter_errors(example), key=lambda error: list(error.absolute_path)
        )
        if errors:
            failures += 1
            print(f"FAIL {example_name}")
            for error in errors:
                print(f"  path={list(error.absolute_path)}: {error.message}")
        else:
            print(f"OK   {example_name} -> {schema_name}")

    if failures:
        print(f"\n{failures} example(s) failed validation")
        return 1
    print(f"\nAll {len(EXAMPLE_TO_SCHEMA)} examples passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
