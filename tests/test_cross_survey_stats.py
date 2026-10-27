"""Cross-survey statistics for one shared question (requirement 8).

The scenarios build several surveys that reuse the same library question, submit
real answers through the public API, and then check the aggregates.
"""

from __future__ import annotations

from typing import Any

from tests.support import (
    add_from_library,
    create_question,
    create_survey,
    number_content,
    publish,
    single_choice_content,
    submit_answer,
    text_content,
)


def survey_with_question(
    client: Any,
    question: dict[str, Any],
    title: str,
    version_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    survey = create_survey(client, title)
    inserted = add_from_library(
        client, survey["id"], version_id or question["latest_version"]["id"]
    )
    publish(client, survey["id"])
    return survey, inserted["question"]["question_id"]


def number_answer(instance_id: str, value: int) -> dict[str, Any]:
    return {"question_id": instance_id, "type": "number", "number": value}


def choice_answer(instance_id: str, option_id: str) -> dict[str, Any]:
    return {
        "question_id": instance_id,
        "type": "single_choice",
        "option_ids": [option_id],
    }


def test_number_stats_across_two_surveys(auth_client, anon) -> None:
    question = create_question(auth_client, number_content())

    first, first_instance = survey_with_question(
        auth_client, question, "问卷一"
    )
    submit_answer(anon, first["slug"], [number_answer(first_instance, 20)])
    submit_answer(anon, first["slug"], [number_answer(first_instance, 30)])

    second, second_instance = survey_with_question(
        auth_client, question, "问卷二"
    )
    submit_answer(anon, second["slug"], [number_answer(second_instance, 40)])

    stats = auth_client.get(f"/api/questions/{question['id']}/stats").json()
    assert stats["answered_count"] == 3
    assert stats["survey_count"] == 2
    assert stats["version_count"] == 1
    assert stats["numeric_count"] == 3
    assert stats["average"] == 30.0
    assert stats["minimum"] == 20
    assert stats["maximum"] == 40
    assert stats["type"] == "number"


def test_version_selector_scopes_the_aggregate(auth_client, anon) -> None:
    question = create_question(auth_client, number_content())
    first, first_instance = survey_with_question(
        auth_client, question, "旧版本问卷"
    )
    submit_answer(anon, first["slug"], [number_answer(first_instance, 20)])

    second_version = auth_client.post(
        f"/api/questions/{question['id']}/versions",
        json={"content": number_content(title="年龄（新口径）")},
    ).json()

    second, second_instance = survey_with_question(
        auth_client, question, "新版本问卷", second_version["id"]
    )
    submit_answer(anon, second["slug"], [number_answer(second_instance, 50)])

    everything = auth_client.get(
        f"/api/questions/{question['id']}/stats?version=all"
    ).json()
    assert everything["answered_count"] == 2
    assert everything["version_count"] == 2
    assert {item["version_no"] for item in everything["versions"]} == {1, 2}

    latest = auth_client.get(
        f"/api/questions/{question['id']}/stats?version=latest"
    ).json()
    assert latest["answered_count"] == 1
    assert latest["average"] == 50.0

    only_first = auth_client.get(
        f"/api/questions/{question['id']}/stats?version=1"
    ).json()
    assert only_first["answered_count"] == 1
    assert only_first["average"] == 20.0


def test_choice_options_merge_by_option_id(auth_client, anon) -> None:
    question = create_question(
        auth_client, single_choice_content(labels=("男", "女"))
    )
    original = {
        option["label"]: option["option_id"]
        for option in question["latest_version"]["content"]["options"]
    }

    first, first_instance = survey_with_question(
        auth_client, question, "性别问卷一"
    )
    submit_answer(anon, first["slug"], [choice_answer(first_instance, original["男"])])
    submit_answer(anon, first["slug"], [choice_answer(first_instance, original["女"])])

    second_version = auth_client.post(
        f"/api/questions/{question['id']}/versions",
        json={
            "content": {
                "type": "single_choice",
                "title": "你的身份是？",
                "required": True,
                "options": [
                    {"option_id": original["男"], "label": "男"},
                    {"option_id": original["女"], "label": "女"},
                    {"option_id": "o_opt_00000099", "label": "其他"},
                ],
            }
        },
    ).json()

    second, second_instance = survey_with_question(
        auth_client, question, "性别问卷二", second_version["id"]
    )
    submit_answer(
        anon, second["slug"], [choice_answer(second_instance, "o_opt_00000099")]
    )

    stats = auth_client.get(f"/api/questions/{question['id']}/stats").json()
    assert stats["answered_count"] == 3
    assert stats["survey_count"] == 2
    counts = {item["label"]: item["count"] for item in stats["option_counts"]}
    assert counts == {"男": 1, "女": 1, "其他": 1}
    # The option set changed between versions, so the flag must be set.
    assert stats["option_set_mismatch"] is True
    assert stats["merged_by"] == "option_id"

    # "其他" only exists in version 2; the per-option version list says so.
    other = next(
        item for item in stats["option_counts"] if item["label"] == "其他"
    )
    assert other["versions"] == [2]

    single_version = auth_client.get(
        f"/api/questions/{question['id']}/stats?version=1"
    ).json()
    assert single_version["answered_count"] == 2
    assert single_version["option_set_mismatch"] is False
    assert [item["label"] for item in single_version["option_counts"]] == [
        "男",
        "女",
    ]


def test_text_answers_are_paged_across_surveys(auth_client, anon) -> None:
    question = create_question(auth_client, text_content())
    first, first_instance = survey_with_question(
        auth_client, question, "建议问卷一"
    )
    submit_answer(
        anon,
        first["slug"],
        [{"question_id": first_instance, "type": "text", "text": "希望多讲聚合"}],
    )
    second, second_instance = survey_with_question(
        auth_client, question, "建议问卷二"
    )
    submit_answer(
        anon,
        second["slug"],
        [{"question_id": second_instance, "type": "text", "text": "希望多讲索引"}],
    )

    stats = auth_client.get(f"/api/questions/{question['id']}/stats").json()
    assert stats["text_count"] == 2
    assert stats["answered_count"] == 2

    page = auth_client.get(
        f"/api/questions/{question['id']}/stats/answers?page=1&page_size=1"
    ).json()
    assert page["total"] == 2
    assert page["total_pages"] == 2
    assert len(page["answers"]) == 1
    assert page["answers"][0]["survey_title"] in {"建议问卷一", "建议问卷二"}

    second_page = auth_client.get(
        f"/api/questions/{question['id']}/stats/answers?page=2&page_size=1"
    ).json()
    assert len(second_page["answers"]) == 1
    assert second_page["answers"][0]["text"] != page["answers"][0]["text"]


def test_survey_filter_narrows_the_aggregate(auth_client, anon) -> None:
    question = create_question(auth_client, number_content())
    first, first_instance = survey_with_question(
        auth_client, question, "限定问卷一"
    )
    submit_answer(anon, first["slug"], [number_answer(first_instance, 20)])
    second, second_instance = survey_with_question(
        auth_client, question, "限定问卷二"
    )
    submit_answer(anon, second["slug"], [number_answer(second_instance, 60)])

    filtered = auth_client.get(
        f"/api/questions/{question['id']}/stats?survey_id={first['id']}"
    ).json()
    assert filtered["answered_count"] == 1
    assert filtered["survey_count"] == 1
    assert filtered["average"] == 20.0


def test_stats_require_access(auth_client, other_client) -> None:
    question = create_question(auth_client, number_content())
    assert (
        other_client.get(f"/api/questions/{question['id']}/stats").status_code
        == 404
    )


def test_legacy_answers_without_reference_are_not_counted(
    auth_client, anon
) -> None:
    """A survey built without the library only counts towards its own stats."""

    question = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "纯手写问卷")
    manual = auth_client.post(
        f"/api/surveys/{survey['id']}/questions",
        json={
            "question_id": "q_manual_0001",
            "type": "number",
            "title": "年龄（周岁）",
            "required": True,
            "validation": {"integer": True, "min": 0, "max": 120},
        },
    )
    assert manual.status_code == 201, manual.text
    publish(auth_client, survey["id"])
    submit_answer(anon, survey["slug"], [number_answer("q_manual_0001", 33)])

    stats = auth_client.get(f"/api/questions/{question['id']}/stats").json()
    assert stats["answered_count"] == 0
    assert stats["survey_count"] == 0
