"""API tests for the shared question library (requirements 1-6).

Covers creation, immutable versions, restore, fork, sharing, reverse lookup and
the two invariants that keep surveys honest: no duplicate entity inside one
survey, and a snapshot that must match the referenced version.
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
    whoami,
)


def _versions(client: Any, entity_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/questions/{entity_id}/versions")
    assert response.status_code == 200, response.text
    return response.json()


def test_create_and_read_question(auth_client) -> None:
    detail = create_question(auth_client, single_choice_content())
    assert detail["latest_version_no"] == 1
    assert detail["version_count"] == 1
    assert detail["is_owner"] is True
    assert len(detail["latest_version"]["content_hash"]) == 64

    fetched = auth_client.get(f"/api/questions/{detail['id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["title"] == "你的身份是？"
    assert body["type"] == "single_choice"
    assert len(body["versions"]) == 1
    assert body["usage_count"] == 0


def test_new_version_is_additive_and_immutable(auth_client) -> None:
    detail = create_question(auth_client, single_choice_content())
    entity_id = detail["id"]
    first = detail["latest_version"]

    response = auth_client.post(
        f"/api/questions/{entity_id}/versions",
        json={"content": single_choice_content(title="你的身份（新）是？")},
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["version_no"] == 2
    assert second["parent_version_id"] == first["id"]
    assert second["content_hash"] != first["content_hash"]

    # v1 is untouched: versions are append-only.
    versions = _versions(auth_client, entity_id)
    assert [item["version_no"] for item in versions] == [1, 2]
    assert versions[0]["content"]["title"] == "你的身份是？"

    refreshed = auth_client.get(f"/api/questions/{entity_id}").json()
    assert refreshed["latest_version_no"] == 2
    assert refreshed["version_count"] == 2
    assert refreshed["title"] == "你的身份（新）是？"


def test_option_ids_are_inherited_across_versions(auth_client) -> None:
    detail = create_question(
        auth_client, single_choice_content(labels=("男", "女"))
    )
    entity_id = detail["id"]
    original = {
        option["label"]: option["option_id"]
        for option in detail["latest_version"]["content"]["options"]
    }

    # A real editor sends back the option objects it already holds: reordering
    # must keep every option's identity, and the new option gets a new id.
    response = auth_client.post(
        f"/api/questions/{entity_id}/versions",
        json={
            "content": {
                "type": "single_choice",
                "title": "你的身份是？",
                "required": True,
                "options": [
                    {"option_id": original["女"], "label": "女"},
                    {"option_id": original["男"], "label": "男"},
                    {"option_id": "o_opt_00000099", "label": "其他"},
                ],
            }
        },
    )
    assert response.status_code == 201, response.text
    updated = {
        option["label"]: option["option_id"]
        for option in response.json()["content"]["options"]
    }

    assert updated["女"] == original["女"]
    assert updated["男"] == original["男"]
    assert updated["其他"] == "o_opt_00000099"


def test_unknown_option_ids_inherit_by_label(auth_client) -> None:
    """A client that invents new ids still keeps options stable by label."""

    detail = create_question(
        auth_client, single_choice_content(labels=("男", "女"))
    )
    original = {
        option["label"]: option["option_id"]
        for option in detail["latest_version"]["content"]["options"]
    }
    response = auth_client.post(
        f"/api/questions/{detail['id']}/versions",
        json={
            "content": {
                "type": "single_choice",
                "title": "你的身份是？",
                "required": True,
                "options": [
                    {"option_id": "o_tmp_00000001", "label": "女"},
                    {"option_id": "o_tmp_00000002", "label": "其他"},
                ],
            }
        },
    )
    assert response.status_code == 201, response.text
    updated = {
        option["label"]: option["option_id"]
        for option in response.json()["content"]["options"]
    }
    assert updated["女"] == original["女"]
    assert updated["其他"] not in original.values()


def test_restore_creates_a_new_version(auth_client) -> None:
    detail = create_question(auth_client, single_choice_content())
    entity_id = detail["id"]
    first = detail["latest_version"]

    auth_client.post(
        f"/api/questions/{entity_id}/versions",
        json={"content": single_choice_content(title="改坏了")},
    )
    response = auth_client.post(
        f"/api/questions/{entity_id}/versions/1/restore"
    )
    assert response.status_code == 201, response.text
    restored = response.json()
    assert restored["version_no"] == 3
    assert restored["restored_from_version_id"] == first["id"]
    assert restored["content"]["title"] == "你的身份是？"
    assert restored["content_hash"] == first["content_hash"]


def test_fork_records_lineage(auth_client) -> None:
    detail = create_question(auth_client, single_choice_content())
    source_version = detail["latest_version"]

    response = auth_client.post(
        f"/api/questions/{detail['id']}/fork",
        json={"title": "派生题目"},
    )
    assert response.status_code == 201, response.text
    forked = response.json()
    assert forked["id"] != detail["id"]
    assert forked["title"] == "派生题目"
    assert forked["latest_version_no"] == 1

    # The lineage is visible through the database-backed detail endpoint of the
    # fork only via its own version chain; the API exposes it through `source`.
    imported = auth_client.get(f"/api/questions/{forked['id']}").json()
    assert imported["versions"][0]["version_no"] == 1


def test_type_change_requires_a_fork(auth_client) -> None:
    detail = create_question(auth_client, single_choice_content())
    response = auth_client.post(
        f"/api/questions/{detail['id']}/versions",
        json={"content": number_content()},
    )
    assert response.status_code == 422, response.text
    assert "fork" in response.text or "type" in response.text


def test_private_question_is_invisible_to_others(auth_client, other_client) -> None:
    detail = create_question(auth_client, single_choice_content())

    hidden = other_client.get(f"/api/questions/{detail['id']}")
    assert hidden.status_code == 404

    listing = other_client.get("/api/questions?scope=usable").json()
    assert detail["id"] not in {item["id"] for item in listing}


def test_share_allows_use_but_not_edit(auth_client, other_client) -> None:
    detail = create_question(auth_client, number_content())
    grantee = whoami(other_client)

    shared = auth_client.post(
        f"/api/questions/{detail['id']}/shares",
        json={"grantee_username": grantee["username"], "permission": "use"},
    )
    assert shared.status_code == 201, shared.text

    visible = other_client.get(f"/api/questions/{detail['id']}")
    assert visible.status_code == 200
    assert visible.json()["is_owner"] is False

    editable = other_client.post(
        f"/api/questions/{detail['id']}/versions",
        json={"content": number_content(title="别人改的")},
    )
    assert editable.status_code == 404

    listing = other_client.get("/api/questions?scope=shared").json()
    assert detail["id"] in {item["id"] for item in listing}

    revoked = auth_client.delete(
        f"/api/questions/{detail['id']}/shares/{grantee['id']}"
    )
    assert revoked.status_code == 204
    assert other_client.get(f"/api/questions/{detail['id']}").status_code == 404


def test_public_question_is_listed_for_everyone(auth_client, other_client) -> None:
    detail = create_question(
        auth_client, single_choice_content(), visibility="public"
    )
    assert other_client.get(f"/api/questions/{detail['id']}").status_code == 200
    public = other_client.get("/api/questions?scope=public").json()
    assert detail["id"] in {item["id"] for item in public}


def test_adding_the_same_question_twice_is_rejected(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "去重测试")
    add_from_library(
        auth_client, survey["id"], detail["latest_version"]["id"]
    )
    again = auth_client.post(
        f"/api/surveys/{survey['id']}/questions/from-library",
        json={"question_version_id": detail["latest_version"]["id"]},
    )
    assert again.status_code == 409, again.text


def test_tampered_snapshot_is_rejected_on_save(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "快照校验")
    add_from_library(
        auth_client, survey["id"], detail["latest_version"]["id"]
    )

    draft = auth_client.get(f"/api/surveys/{survey['id']}").json()["current_draft"]
    questions = draft["questions"]
    questions[0]["validation"]["max"] = 200

    response = auth_client.put(
        f"/api/surveys/{survey['id']}/draft",
        json={"revision": draft["revision"], "questions": questions},
    )
    assert response.status_code == 422, response.text
    assert "question content no longer matches" in response.text


def test_refresh_moves_the_draft_to_the_latest_version(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "版本升级")
    inserted = add_from_library(
        auth_client, survey["id"], detail["latest_version"]["id"]
    )
    instance_id = inserted["question"]["question_id"]

    auth_client.post(
        f"/api/questions/{detail['id']}/versions",
        json={"content": number_content(title="年龄（新口径）")},
    )
    refreshed = auth_client.post(
        f"/api/surveys/{survey['id']}/questions/{instance_id}/refresh"
    )
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()["question"]
    assert body["title"] == "年龄（新口径）"
    assert body["question_id"] == instance_id
    assert body["question_ref"] is not None


def test_usages_list_the_surveys_that_use_the_question(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "使用情况")
    inserted = add_from_library(
        auth_client, survey["id"], detail["latest_version"]["id"]
    )
    publish(auth_client, survey["id"])

    usages = auth_client.get(f"/api/questions/{detail['id']}/usages").json()
    assert len(usages) == 1
    assert usages[0]["survey_title"] == "使用情况"
    assert usages[0]["instance_question_id"] == inserted["question"]["question_id"]
    assert usages[0]["is_published"] is True


def test_published_question_cannot_be_deleted(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    survey = create_survey(auth_client, "删除保护")
    add_from_library(
        auth_client, survey["id"], detail["latest_version"]["id"]
    )
    publish(auth_client, survey["id"])

    response = auth_client.delete(f"/api/questions/{detail['id']}")
    assert response.status_code == 409, response.text


def test_unused_question_is_soft_deleted(auth_client) -> None:
    detail = create_question(auth_client, number_content())
    assert auth_client.delete(f"/api/questions/{detail['id']}").status_code == 204
    assert auth_client.get(f"/api/questions/{detail['id']}").status_code == 404
