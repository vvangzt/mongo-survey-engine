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

    print("\nPydantic contract and engine checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
