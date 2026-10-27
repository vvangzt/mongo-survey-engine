"""API tests for question banks (requirement 7)."""

from __future__ import annotations

from typing import Any

from tests.support import (
    create_question,
    number_content,
    single_choice_content,
)


def _create_library(
    client: Any,
    name: str,
    *,
    visibility: str = "private",
    description: str = "",
) -> dict[str, Any]:
    response = client.post(
        "/api/libraries",
        json={"name": name, "description": description, "visibility": visibility},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_libraries(auth_client) -> None:
    library = _create_library(auth_client, "课程通用题目", description="常用题")
    assert library["item_count"] == 0
    assert library["is_owner"] is True

    listing = auth_client.get("/api/libraries").json()
    assert [item["id"] for item in listing] == [library["id"]]


def test_duplicate_library_name_is_rejected(auth_client) -> None:
    _create_library(auth_client, "重名题库")
    response = auth_client.post(
        "/api/libraries", json={"name": "重名题库", "description": ""}
    )
    assert response.status_code == 409, response.text


def test_add_and_remove_library_items(auth_client) -> None:
    library = _create_library(auth_client, "选题库")
    question = create_question(auth_client, number_content())

    added = auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={
            "entity_id": question["id"],
            "note": "跨问卷统计示例",
            "tags": ["人口学", "数值"],
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["title"] == "年龄（周岁）"
    assert added.json()["latest_version_no"] == 1

    detail = auth_client.get(f"/api/libraries/{library['id']}").json()
    assert [item["entity_id"] for item in detail["items"]] == [question["id"]]
    assert detail["items"][0]["note"] == "跨问卷统计示例"
    assert detail["item_count"] == 1

    removed = auth_client.delete(
        f"/api/libraries/{library['id']}/items/{question['id']}"
    )
    assert removed.status_code == 204
    assert auth_client.get(f"/api/libraries/{library['id']}").json()["items"] == []


def test_adding_the_same_item_twice_is_idempotent(auth_client) -> None:
    library = _create_library(auth_client, "幂等题库")
    question = create_question(auth_client, number_content())

    first = auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )
    second = auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    detail = auth_client.get(f"/api/libraries/{library['id']}").json()
    assert len(detail["items"]) == 1


def test_library_scope_lists_its_questions(auth_client) -> None:
    library = _create_library(auth_client, "范围题库")
    question = create_question(auth_client, single_choice_content())
    auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )
    listing = auth_client.get("/api/questions?scope=library").json()
    assert question["id"] in {item["id"] for item in listing}


def test_delete_library_removes_items_but_keeps_questions(auth_client) -> None:
    library = _create_library(auth_client, "待删题库")
    question = create_question(auth_client, number_content())
    auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )

    assert auth_client.delete(f"/api/libraries/{library['id']}").status_code == 204
    assert auth_client.get(f"/api/libraries/{library['id']}").status_code == 404
    # The question itself is untouched.
    assert auth_client.get(f"/api/questions/{question['id']}").status_code == 200


def test_private_library_is_hidden_from_others(auth_client, other_client) -> None:
    library = _create_library(auth_client, "私有题库")
    assert other_client.get(f"/api/libraries/{library['id']}").status_code == 404
    listing = other_client.get("/api/libraries").json()
    assert library["id"] not in {item["id"] for item in listing}


def test_public_library_is_readable_but_not_writable(
    auth_client, other_client
) -> None:
    library = _create_library(auth_client, "公开题库", visibility="public")
    question = create_question(
        auth_client, number_content(), visibility="public"
    )
    auth_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )

    readable = other_client.get(f"/api/libraries/{library['id']}")
    assert readable.status_code == 200
    assert readable.json()["is_owner"] is False
    assert len(readable.json()["items"]) == 1

    writable = other_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": question["id"]},
    )
    assert writable.status_code == 404


def test_adding_a_question_i_cannot_use_is_rejected(
    auth_client, other_client
) -> None:
    library = _create_library(other_client, "别人的题库")
    private_question = create_question(auth_client, number_content())
    response = other_client.post(
        f"/api/libraries/{library['id']}/items",
        json={"entity_id": private_question["id"]},
    )
    assert response.status_code == 404, response.text


def test_update_library_metadata(auth_client) -> None:
    library = _create_library(auth_client, "旧名字")
    response = auth_client.patch(
        f"/api/libraries/{library['id']}",
        json={"name": "新名字", "visibility": "public"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "新名字"
    assert response.json()["visibility"] == "public"
