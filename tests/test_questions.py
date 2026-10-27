"""Unit tests for the shared question library domain models (no database)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import ObjectId
from pydantic import TypeAdapter, ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas.pydantic import (  # noqa: E402
    QuestionContent,
    QuestionVersion,
    content_of,
    hash_content,
    merge_option_ids,
    question_from_content,
)
from schemas.pydantic.models import Option, Question  # noqa: E402

CONTENT_ADAPTER: TypeAdapter[QuestionContent] = TypeAdapter(QuestionContent)
QUESTION_ADAPTER: TypeAdapter[Question] = TypeAdapter(Question)
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def single_choice_options(*labels: str) -> list[dict[str, str]]:
    return [
        {"option_id": f"o_opt_{index:08d}", "label": label}
        for index, label in enumerate(labels)
    ]


def single_choice_content(title: str = "你的身份是？") -> dict:
    return {
        "type": "single_choice",
        "title": title,
        "required": True,
        "options": single_choice_options("学生", "教师"),
    }


def version_document(
    *,
    version_no: int = 1,
    parent: ObjectId | None = None,
    content: dict | None = None,
    entity_id: ObjectId | None = None,
) -> dict:
    parsed = CONTENT_ADAPTER.validate_python(content or single_choice_content())
    return {
        "_id": str(ObjectId()),
        "entity_id": str(entity_id or ObjectId()),
        "version_no": version_no,
        "parent_version_id": str(parent) if parent else None,
        "restored_from_version_id": None,
        "content": parsed.model_dump(mode="json", exclude_none=True),
        "content_hash": hash_content(parsed),
        "created_by": str(ObjectId()),
        "created_at": NOW,
    }


# ---------------------------------------------------------------------------
# content <-> question round trip
# ---------------------------------------------------------------------------


def test_content_round_trip_preserves_the_question() -> None:
    question = QUESTION_ADAPTER.validate_python(
        {
            "question_id": "q_single_0001",
            "type": "single_choice",
            "title": "你的身份是？",
            "description": "用于分组统计",
            "required": True,
            "options": single_choice_options("学生", "教师"),
            "logic": {"fallback": {"action": "next"}, "rules": []},
        }
    )
    content = content_of(question)
    assert content.type == "single_choice"
    assert content.required is True
    assert len(content.options) == 2  # type: ignore[attr-defined]

    rebuilt = question_from_content(content, "q_single_0002")
    assert rebuilt.question_id == "q_single_0002"
    assert rebuilt.title == question.title
    assert rebuilt.logic is None
    assert hash_content(content_of(rebuilt)) == hash_content(content)


def test_hash_ignores_instance_id_and_logic() -> None:
    """Two surveys embedding the same content hash identically."""

    base = {
        "type": "text",
        "title": "补充建议",
        "required": False,
        "validation": {"min_length": 0, "max_length": 200, "trim": True},
    }
    first = QUESTION_ADAPTER.validate_python(
        {**base, "question_id": "q_text_0001"}
    )
    second = QUESTION_ADAPTER.validate_python(
        {
            **base,
            "question_id": "q_text_0002",
            "logic": {"fallback": {"action": "end"}, "rules": []},
        }
    )
    assert hash_content(content_of(first)) == hash_content(content_of(second))


def test_hash_changes_when_content_changes() -> None:
    one = CONTENT_ADAPTER.validate_python(single_choice_content())
    two = CONTENT_ADAPTER.validate_python(
        single_choice_content(title="你的职业是？")
    )
    assert hash_content(one) != hash_content(two)


# ---------------------------------------------------------------------------
# version chain rules
# ---------------------------------------------------------------------------


def test_first_version_cannot_have_a_parent() -> None:
    with pytest.raises(ValidationError):
        QuestionVersion.model_validate(
            version_document(version_no=1, parent=ObjectId())
        )


def test_later_version_requires_a_parent() -> None:
    with pytest.raises(ValidationError):
        QuestionVersion.model_validate(version_document(version_no=2))


def test_version_rejects_a_stale_content_hash() -> None:
    document = version_document(version_no=2, parent=ObjectId())
    document["content"]["title"] = "被篡改"
    with pytest.raises(ValidationError):
        QuestionVersion.model_validate(document)


def test_chain_of_three_versions_links_up() -> None:
    entity_id = ObjectId()
    first = QuestionVersion.model_validate(
        version_document(version_no=1, entity_id=entity_id)
    )
    second = QuestionVersion.model_validate(
        version_document(
            version_no=2, parent=ObjectId(first.id), entity_id=entity_id
        )
    )
    third = QuestionVersion.model_validate(
        version_document(
            version_no=3, parent=ObjectId(second.id), entity_id=entity_id
        )
    )
    assert second.parent_version_id == first.id
    assert third.parent_version_id == second.id
    assert third.entity_id == first.entity_id


# ---------------------------------------------------------------------------
# option identity across versions (invariant I6)
# ---------------------------------------------------------------------------


def test_unchanged_label_inherits_the_option_id() -> None:
    previous = [
        Option(option_id="o_male_000001", label="男"),
        Option(option_id="o_female_0001", label="女"),
    ]
    merged = merge_option_ids(
        previous,
        [
            Option(option_id="o_temp_0000001", label="女"),
            Option(option_id="o_temp_0000002", label="其他"),
        ],
    )
    assert merged[0].option_id == "o_female_0001"
    assert merged[1].option_id not in {"o_male_000001", "o_female_0001"}


def test_existing_id_is_kept_even_if_the_label_changes() -> None:
    previous = [Option(option_id="o_male_000001", label="男")]
    merged = merge_option_ids(
        previous, [Option(option_id="o_male_000001", label="男性")]
    )
    assert merged[0].option_id == "o_male_000001"
    assert merged[0].label == "男性"


def test_removed_option_disappears_from_the_new_version() -> None:
    previous = [
        Option(option_id="o_male_000001", label="男"),
        Option(option_id="o_female_0001", label="女"),
    ]
    merged = merge_option_ids(
        previous, [Option(option_id="o_female_0001", label="女")]
    )
    assert [option.option_id for option in merged] == ["o_female_0001"]


def test_collision_is_resolved_with_a_fresh_id() -> None:
    previous = [
        Option(option_id="o_a_000000001", label="甲"),
        Option(option_id="o_b_000000001", label="乙"),
    ]
    merged = merge_option_ids(
        previous,
        [
            Option(option_id="o_a_000000001", label="甲"),
            Option(option_id="o_a_000000001", label="丙"),
        ],
    )
    assert merged[0].option_id == "o_a_000000001"
    assert merged[1].option_id != "o_a_000000001"
    assert merged[1].label == "丙"


# ---------------------------------------------------------------------------
# content validation still applies to library content
# ---------------------------------------------------------------------------


def test_duplicate_option_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CONTENT_ADAPTER.validate_python(
            {
                "type": "single_choice",
                "title": "重复选项",
                "options": [
                    {"option_id": "o_a_000000009", "label": "甲"},
                    {"option_id": "o_a_000000009", "label": "乙"},
                ],
            }
        )


def test_multi_choice_bounds_cannot_exceed_option_count() -> None:
    with pytest.raises(ValidationError):
        CONTENT_ADAPTER.validate_python(
            {
                "type": "multi_choice",
                "title": "水果",
                "options": single_choice_options("苹果", "香蕉"),
                "validation": {"min_selected": 3},
            }
        )


def test_number_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        CONTENT_ADAPTER.validate_python(
            {
                "type": "number",
                "title": "年龄",
                "validation": {"integer": True, "min": 100, "max": 10},
            }
        )
