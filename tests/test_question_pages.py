"""Page-level smoke tests for the phase-2 screens.

These are the automated equivalent of clicking through the new UI: every page
must render for its owner, hide itself from strangers, and require a login.
"""

from __future__ import annotations

from tests.support import (
    add_from_library,
    anonymous_client,
    create_question,
    create_survey,
    number_content,
    publish,
)


def test_question_pages_render(auth_client) -> None:
    question = create_question(auth_client, number_content())

    listing = auth_client.get("/questions")
    assert listing.status_code == 200
    assert "题目库" in listing.text

    detail = auth_client.get(f"/questions/{question['id']}")
    assert detail.status_code == 200
    assert "版本历史" in detail.text

    stats = auth_client.get(f"/questions/{question['id']}/stats")
    assert stats.status_code == 200
    assert "跨问卷统计" in stats.text


def test_library_pages_render(auth_client) -> None:
    library = auth_client.post(
        "/api/libraries", json={"name": "页面题库", "description": ""}
    ).json()
    question = create_question(auth_client, number_content())
    auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )

    listing = auth_client.get("/libraries")
    assert listing.status_code == 200
    assert "题库" in listing.text

    detail = auth_client.get(f"/libraries/{library['id']}")
    assert detail.status_code == 200
    assert "题库内容" in detail.text


def test_editor_page_has_the_library_picker(auth_client) -> None:
    survey = create_survey(auth_client, "编辑器页面")
    response = auth_client.get(f"/surveys/{survey['id']}/edit")
    assert response.status_code == 200
    assert "从题库插入" in response.text
    assert "editor_library.js" in response.text


def test_editor_insert_and_refresh_via_api(auth_client) -> None:
    """The editor's two library actions, exercised the way the page calls them."""

    question = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "编辑器插入")
    inserted = add_from_library(
        auth_client, survey["id"], question["latest_version"]["id"]
    )
    instance_id = inserted["question"]["question_id"]

    auth_client.post(
        f"/api/questions/{question['id']}/versions",
        json={"content": number_content(title="年龄（新）")},
    )
    refreshed = auth_client.post(
        f"/api/surveys/{survey['id']}/questions/{instance_id}/refresh"
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["question"]["title"] == "年龄（新）"


def test_question_page_is_hidden_from_strangers(auth_client, other_client) -> None:
    question = create_question(auth_client, number_content())
    response = other_client.get(f"/questions/{question['id']}")
    assert response.status_code == 404
    assert "题目不存在" in response.text


def test_pages_require_login(api_base_url: str) -> None:
    client = anonymous_client(api_base_url)
    try:
        for path in ("/questions", "/libraries"):
            response = client.get(path, allow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"].startswith("/login")
    finally:
        client.close()


def test_static_assets_for_new_pages_are_served(api_base_url: str) -> None:
    client = anonymous_client(api_base_url)
    try:
        for path in (
            "/static/js/question_form.js",
            "/static/js/questions.js",
            "/static/js/question_detail.js",
            "/static/js/libraries.js",
            "/static/js/library_detail.js",
            "/static/js/question_stats.js",
            "/static/js/editor_library.js",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "javascript" in response.headers.get("content-type", "")
    finally:
        client.close()


def test_cross_survey_stats_page_shows_numbers(auth_client, anon) -> None:
    question = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "统计页面")
    inserted = add_from_library(
        auth_client, survey["id"], question["latest_version"]["id"]
    )
    publish(auth_client, survey["id"])
    auth_client.post(
        f"/api/public/surveys/{survey['slug']}/responses",
        json={
            "answers": [
                {
                    "question_id": inserted["question"]["question_id"],
                    "type": "number",
                    "number": 28,
                }
            ],
            "is_anonymous": True,
            "submission_token": "a" * 24,
        },
    )

    page = auth_client.get(f"/questions/{question['id']}/stats")
    assert page.status_code == 200

    data = auth_client.get(f"/api/questions/{question['id']}/stats").json()
    assert data["answered_count"] == 1
    assert data["average"] == 28.0
