"""Compatibility tests: phase-1 data and requests must keep working unchanged.

The rest of the suite already exercises the old behaviour; this module pins the
specific claims the report makes about backward compatibility.
"""

from __future__ import annotations

from typing import Any

import pytest
from bson import ObjectId
from pymongo import MongoClient

from tests.support import (
    add_from_library,
    create_question,
    create_survey,
    number_content,
    publish,
    submit_answer,
)


def number_question(question_id: str = "q_manual_0001") -> dict[str, Any]:
    """A question payload exactly as phase 1 accepted it."""

    return {
        "question_id": question_id,
        "type": "number",
        "title": "年龄（周岁）",
        "required": True,
        "validation": {"integer": True, "min": 0, "max": 120},
    }


def test_phase1_question_payload_has_no_reference(auth_client) -> None:
    survey = create_survey(auth_client, "历史问卷")
    response = auth_client.post(
        f"/api/surveys/{survey['id']}/questions", json=number_question()
    )
    assert response.status_code == 201, response.text
    body = response.json()["question"]
    assert body["question_id"] == "q_manual_0001"
    assert "question_ref" not in body or body["question_ref"] is None

    draft = auth_client.get(f"/api/surveys/{survey['id']}").json()["current_draft"]
    assert all(
        question.get("question_ref") is None
        for question in draft["questions"]
    )


def test_phase1_version_document_is_still_served(
    auth_client, anon, mongo_uri, test_database_name
) -> None:
    """Force the stored draft back to the phase-1 shape, then use it end to end."""

    survey = create_survey(auth_client, "被降级的问卷")
    auth_client.post(
        f"/api/surveys/{survey['id']}/questions", json=number_question()
    )

    client = MongoClient(mongo_uri)
    try:
        client[test_database_name]["survey_versions"].update_one(
            {
                "survey_id": ObjectId(survey["id"]),
                "state": "draft",
            },
            {"$set": {"content_schema_version": 1}},
        )
    finally:
        client.close()

    published = publish(auth_client, survey["id"])
    assert published["version_no"] == 1

    submit_answer(anon, survey["slug"], [{"question_id": "q_manual_0001", "type": "number", "number": 42}])

    client = MongoClient(mongo_uri)
    try:
        response = client[test_database_name]["responses"].find_one(
            {"survey_id": ObjectId(survey["id"])}
        )
        assert response is not None
        answer = response["answers"][0]
        assert answer["question_id"] == "q_manual_0001"
        # No library reference was invented for legacy data.
        assert "question_ref" not in answer
    finally:
        client.close()

    stats = auth_client.get(f"/api/surveys/{survey['id']}/stats")
    assert stats.status_code == 200, stats.text
    assert stats.json()["response_count"] == 1


def test_draft_can_mix_library_and_handwritten_questions(
    auth_client, anon
) -> None:
    """The two authoring styles coexist inside one survey version."""

    shared = create_question(auth_client, number_content(title="共享年龄题"))
    survey = create_survey(auth_client, "混合问卷")
    add_from_library(
        auth_client, survey["id"], shared["latest_version"]["id"]
    )
    manual = auth_client.post(
        f"/api/surveys/{survey['id']}/questions",
        json=number_question("q_manual_0002"),
    )
    assert manual.status_code == 201, manual.text

    draft = auth_client.get(f"/api/surveys/{survey['id']}").json()["current_draft"]
    refs = [
        question["question_id"]
        for question in draft["questions"]
        if question.get("question_ref")
    ]
    assert len(refs) == 1

    publish(auth_client, survey["id"])
    submit_answer(
        anon,
        survey["slug"],
        [
            {"question_id": refs[0], "type": "number", "number": 30},
            {"question_id": "q_manual_0002", "type": "number", "number": 31},
        ],
    )

    # Only the shared question feeds the cross-survey aggregate.
    stats = auth_client.get(f"/api/questions/{shared['id']}/stats").json()
    assert stats["answered_count"] == 1
    assert stats["average"] == 30.0

    # The survey-level statistics still cover both questions.
    own_stats = auth_client.get(f"/api/surveys/{survey['id']}/stats").json()
    assert own_stats["response_count"] == 1
    assert len(own_stats["questions"]) == 2


def test_draft_update_accepts_the_old_request_shape(auth_client) -> None:
    survey = create_survey(auth_client, "旧请求体")
    auth_client.post(
        f"/api/surveys/{survey['id']}/questions", json=number_question()
    )
    draft = auth_client.get(f"/api/surveys/{survey['id']}").json()["current_draft"]

    questions = draft["questions"]
    for question in questions:
        question.pop("question_ref", None)

    response = auth_client.put(
        f"/api/surveys/{survey['id']}/draft",
        json={"revision": draft["revision"], "questions": questions},
    )
    assert response.status_code == 200, response.text
    assert response.json()["questions"][0]["title"] == "年龄（周岁）"


def test_phase1_like_response_documents_are_readable(
    auth_client, mongo_uri, test_database_name
) -> None:
    """A response without any question_ref must still be visible to statistics."""

    survey = create_survey(auth_client, "无引用答卷")
    auth_client.post(
        f"/api/surveys/{survey['id']}/questions", json=number_question()
    )
    published = publish(auth_client, survey["id"])

    client = MongoClient(mongo_uri)
    try:
        client[test_database_name]["responses"].insert_one(
            {
                "_id": ObjectId(),
                "schema_version": 1,
                "survey_id": ObjectId(survey["id"]),
                "survey_version_id": ObjectId(published["survey_version_id"]),
                "respondent_id": None,
                "is_anonymous": True,
                "submission_token": "legacy-token-0123456789",
                "answers": [
                    {
                        "question_id": "q_manual_0001",
                        "type": "number",
                        "number": 50,
                    }
                ],
                "submitted_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            }
        )
    finally:
        client.close()

    stats = auth_client.get(f"/api/surveys/{survey['id']}/stats")
    assert stats.status_code == 200, stats.text
    payload = stats.json()
    assert payload["response_count"] == 1
    number_stats = next(
        item
        for item in payload["questions"]
        if item["question_id"] == "q_manual_0001"
    )
    assert number_stats["answered_count"] == 1
    assert number_stats["average"] == 50.0
