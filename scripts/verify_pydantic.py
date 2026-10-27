"""Smoke-test the Pydantic contract and the reference jump-logic engine."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.pydantic import (  # noqa: E402
    Response,
    Survey,
    SurveyStatSnapshot,
    SurveyVersion,
    SubmissionValidationError,
    User,
    validate_response,
)

EXAMPLES = ROOT / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def expect_validation_error(label: str, fn) -> None:
    try:
        fn()
    except ValidationError:
        print(f"OK   rejected {label}")
        return
    raise AssertionError(f"expected ValidationError for {label}")


def main() -> int:
    user = User.model_validate(load("users.example.json"))
    survey = Survey.model_validate(load("surveys.example.json"))
    version_data = load("survey_versions.example.json")
    version = SurveyVersion.model_validate(version_data)
    response_anon = Response.model_validate(
        load("responses.anonymous.example.json")
    )
    response_short = Response.model_validate(
        load("responses.identified-short-path.example.json")
    )
    snapshot = SurveyStatSnapshot.model_validate(
        load("survey_stat_snapshots.example.json")
    )

    long_result = validate_response(version, response_anon)
    short_result = validate_response(version, response_short)
    expected_long = (
        "q_role_0001",
        "q_resources_0002",
        "q_nolab_0003",
        "q_rating_0004",
        "q_improve_0005",
        "q_recommend_0006",
    )
    expected_short = (
        "q_role_0001",
        "q_resources_0002",
        "q_rating_0004",
        "q_recommend_0006",
    )
    assert long_result.path == expected_long, long_result.path
    assert short_result.path == expected_short, short_result.path
    assert len(short_result.answers) == 4

    print("OK   models parsed:", user.email, survey.slug, snapshot.response_count)
    print("OK   long path :", " -> ".join(long_result.path))
    print("OK   short path:", " -> ".join(short_result.path))

    # A hidden question's answer must not influence logic or be persisted.
    hidden_extra = copy.deepcopy(
        load("responses.identified-short-path.example.json")
    )
    hidden_extra["answers"].append(
        {
            "question_id": "q_improve_0005",
            "type": "text",
            "text": "这段内容位于未展示分支，应被拒绝",
        }
    )
    hidden_response = Response.model_validate(hidden_extra)
    try:
        validate_response(version, hidden_response)
    except SubmissionValidationError:
        print("OK   rejected answer for a hidden branch")
    else:
        raise AssertionError("hidden answer was accepted")

    # Required question on the computed path cannot be omitted.
    missing_required = copy.deepcopy(
        load("responses.identified-short-path.example.json")
    )
    missing_required["answers"] = [
        answer
        for answer in missing_required["answers"]
        if answer["question_id"] != "q_rating_0004"
    ]
    try:
        validate_response(version, Response.model_validate(missing_required))
    except SubmissionValidationError:
        print("OK   rejected missing required answer")
    else:
        raise AssertionError("missing required answer was accepted")

    # Publish-time semantic validation must reject a backward jump.
    backward = copy.deepcopy(version_data)
    backward["questions"][3]["logic"]["rules"][0]["then"][
        "target_question_id"
    ] = "q_nolab_0003"
    expect_validation_error(
        "backward jump", lambda: SurveyVersion.model_validate(backward)
    )

    # Publish-time semantic validation must reject a mismatched operator value.
    bad_operator = copy.deepcopy(version_data)
    bad_operator["questions"][3]["logic"]["rules"][0]["when"]["conditions"][0][
        "operator"
    ] = "includes_any"
    expect_validation_error(
        "number question with multi-choice operator",
        lambda: SurveyVersion.model_validate(bad_operator),
    )

    # Referential integrity: an unknown option cannot be used in a condition.
    bad_option = copy.deepcopy(version_data)
    bad_option["questions"][0]["logic"]["rules"][0]["when"]["conditions"][0][
        "value"
    ] = "o_does_not_exist"
    expect_validation_error(
        "condition with unknown option",
        lambda: SurveyVersion.model_validate(bad_option),
    )

    verify_question_library()

    print("\nPydantic contract and engine checks passed")
    return 0


def verify_question_library() -> None:
    """Phase-2 question-library contract: entities, versions and references."""

    from pydantic import TypeAdapter

    from schemas.pydantic import (
        QuestionContent,
        QuestionEntity,
        QuestionLibrary,
        QuestionLibraryItem,
        QuestionShare,
        QuestionVersion,
        content_of,
        hash_content,
        merge_option_ids,
        question_from_content,
    )
    from schemas.pydantic.models import Option

    entity = QuestionEntity.model_validate(load("questions.example.json"))
    version = QuestionVersion.model_validate(load("question_versions.example.json"))
    share = QuestionShare.model_validate(load("question_shares.example.json"))
    library = QuestionLibrary.model_validate(load("question_libraries.example.json"))
    item = QuestionLibraryItem.model_validate(load("question_library_items.example.json"))

    assert str(entity.latest_version_id) == str(version.id), "latest_version_id must point at the newest version"
    assert str(version.entity_id) == str(entity.id)
    assert str(item.entity_id) == str(entity.id)
    assert str(item.library_id) == str(library.id)
    assert str(share.entity_id) == str(entity.id)
    # The model itself re-derives the hash and rejects a mismatch.
    assert version.content_hash == hash_content(version.content)
    print("OK   question library documents parsed:", entity.type, version.version_no, library.name)

    # A survey version may carry library references without losing its shape.
    ref_version_data = load("survey_versions.with_library_refs.example.json")
    ref_version = SurveyVersion.model_validate(ref_version_data)
    assert ref_version.content_schema_version == 2
    referenced = [question for question in ref_version.questions if question.question_ref]
    assert len(referenced) == 2, referenced
    print(
        "OK   survey version with question_ref:",
        ", ".join(question.question_id for question in referenced),
    )

    # Snapshot == referenced content, so the cross-survey identity is honest.
    for question in referenced:
        content = content_of(question)
        rebuilt = question_from_content(content, question.question_id)
        assert hash_content(content_of(rebuilt)) == hash_content(content)
    print("OK   embedded snapshot round-trips through the library content")

    response_refs = Response.model_validate(
        load("responses.with_library_refs.example.json")
    )
    assert sum(1 for answer in response_refs.answers if answer.question_ref) == 2
    print("OK   response answers may carry question_ref:", len(response_refs.answers))

    # A phase-1 document (no references at all) must stay valid.
    legacy_version = SurveyVersion.model_validate(
        load("survey_versions.example.json")
    )
    assert all(
        question.question_ref is None for question in legacy_version.questions
    )
    assert legacy_version.content_schema_version == 1
    print("OK   phase-1 version without question_ref still validates")

    # Tampering with the content while keeping the old hash must be rejected.
    tampered = copy.deepcopy(load("question_versions.example.json"))
    tampered["content"]["title"] = "被篡改的标题"
    expect_validation_error(
        "question version with a stale content_hash",
        lambda: QuestionVersion.model_validate(tampered),
    )

    # v1 cannot have a parent; v2 must have one.
    orphan = copy.deepcopy(load("question_versions.example.json"))
    orphan["version_no"] = 1
    expect_validation_error(
        "first question version with a parent",
        lambda: QuestionVersion.model_validate(orphan),
    )
    missing_parent = copy.deepcopy(load("question_versions.example.json"))
    missing_parent["parent_version_id"] = None
    expect_validation_error(
        "later question version without a parent",
        lambda: QuestionVersion.model_validate(missing_parent),
    )

    # I6: option ids survive across versions so cross-version stats can merge.
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
    assert merged[0].option_id == "o_female_0001", merged
    assert merged[1].option_id not in {"o_male_000001", "o_female_0001"}
    print("OK   option_id inherited by label:", merged[0].option_id)

    # All four discriminator branches of QuestionContent must parse.
    content_adapter = TypeAdapter(QuestionContent)
    for payload in (
        {
            "type": "single_choice",
            "title": "性别",
            "options": [
                {"option_id": "o_a_000000001", "label": "男"},
                {"option_id": "o_b_000000001", "label": "女"},
            ],
        },
        {
            "type": "multi_choice",
            "title": "水果",
            "options": [
                {"option_id": "o_a_000000002", "label": "苹果"},
                {"option_id": "o_b_000000002", "label": "香蕉"},
            ],
            "validation": {"min_selected": 1, "max_selected": 2},
        },
        {
            "type": "text",
            "title": "建议",
            "validation": {"max_length": 200},
        },
        {
            "type": "number",
            "title": "年龄",
            "validation": {"integer": True, "min": 0, "max": 120},
        },
    ):
        parsed = content_adapter.validate_python(payload)
        assert len(hash_content(parsed)) == 64
    print("OK   QuestionContent parses all four types")

    # Duplicate option ids inside one question are still rejected.
    expect_validation_error(
        "duplicate option ids in library content",
        lambda: content_adapter.validate_python(
            {
                "type": "single_choice",
                "title": "重复选项",
                "options": [
                    {"option_id": "o_a_000000009", "label": "甲"},
                    {"option_id": "o_a_000000009", "label": "乙"},
                ],
            }
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
