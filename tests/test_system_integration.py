"""End-to-end API integration tests using real registration and cookie auth."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient

from tests.support import ApiClient

TIMEOUT = 15


def q_gate() -> dict:
    return {
        "question_id": "q_gate_0001",
        "type": "single_choice",
        "title": "你是否使用过实验环境？",
        "required": True,
        "options": [
            {"option_id": "o_yes_0000001", "label": "是"},
            {"option_id": "o_no_00000001", "label": "否"},
        ],
        "logic": {
            "fallback": {"action": "next"},
            "rules": [
                {
                    "rule_id": "r_skip_0001",
                    "when": {
                        "mode": "all",
                        "conditions": [
                            {
                                "question_id": "q_gate_0001",
                                "operator": "eq",
                                "value": "o_no_00000001",
                            }
                        ],
                    },
                    "then": {
                        "action": "goto",
                        "target_question_id": "q_text_0004",
                    },
                }
            ],
        },
    }


def q_multi() -> dict:
    return {
        "question_id": "q_multi_0002",
        "type": "multi_choice",
        "title": "你使用过哪些资源？",
        "required": True,
        "options": [
            {"option_id": "o_opt_a_0001", "label": "A 课件"},
            {"option_id": "o_opt_b_0001", "label": "B 视频"},
            {"option_id": "o_opt_c_0001", "label": "C 实验"},
            {"option_id": "o_opt_d_0001", "label": "D 讨论"},
        ],
        "validation": {"min_selected": 2, "max_selected": 3},
    }


def q_number() -> dict:
    return {
        "question_id": "q_number_0003",
        "type": "number",
        "title": "每周学习时长（小时）",
        "required": True,
        "validation": {"integer": True, "min": 18, "max": 60},
    }


def q_text() -> dict:
    return {
        "question_id": "q_text_0004",
        "type": "text",
        "title": "补充建议",
        "required": False,
        "validation": {"min_length": 0, "max_length": 500, "trim": True},
    }


def create_survey(
    client: ApiClient,
    *,
    allow_anonymous: bool = True,
    allow_multiple_responses: bool = True,
    title: str = "数据库课程体验调查",
) -> dict:
    response = client.post(
        "/api/surveys",
        json={
            "title": title,
            "description": "系统测试问卷",
            "allow_anonymous": allow_anonymous,
            "allow_multiple_responses": allow_multiple_responses,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_question(client: ApiClient, survey_id: str, question: dict) -> dict:
    response = client.post(
        f"/api/surveys/{survey_id}/questions", json=question
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish_survey(client: ApiClient, survey_id: str) -> dict:
    response = client.post(f"/api/surveys/{survey_id}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def create_published_survey(
    client: ApiClient,
    *,
    allow_anonymous: bool = True,
    allow_multiple_responses: bool = True,
) -> dict:
    survey = create_survey(
        client,
        allow_anonymous=allow_anonymous,
        allow_multiple_responses=allow_multiple_responses,
    )
    for question in (q_gate(), q_multi(), q_number(), q_text()):
        add_question(client, survey["id"], question)
    published = publish_survey(client, survey["id"])
    return {**survey, **published, "id": survey["id"]}


@pytest.fixture
def published_survey(auth_client: ApiClient) -> dict:
    return create_published_survey(auth_client)


def single(option_id: str = "o_yes_0000001") -> dict:
    return {
        "question_id": "q_gate_0001",
        "type": "single_choice",
        "option_ids": [option_id],
    }


def multi(option_ids: list[str]) -> dict:
    return {
        "question_id": "q_multi_0002",
        "type": "multi_choice",
        "option_ids": option_ids,
    }


def number(value: int) -> dict:
    return {
        "question_id": "q_number_0003",
        "type": "number",
        "number": value,
    }


def text(value: str) -> dict:
    return {
        "question_id": "q_text_0004",
        "type": "text",
        "text": value,
    }


def submit(
    client: ApiClient,
    survey_id: str,
    answers: list[dict],
    *,
    anonymous: bool,
):
    return client.post(
        f"/api/surveys/{survey_id}/responses",
        json={
            "answers": answers,
            "is_anonymous": anonymous,
            "submission_token": str(uuid.uuid4()),
        },
    )


def test_create_survey(auth_client: ApiClient) -> None:
    payload = create_survey(auth_client)
    assert payload["status"] == "draft"
    assert payload["allow_anonymous"] is True
    assert payload["allow_multiple_responses"] is True
    assert payload["slug"]
    assert payload["current_draft_version_id"]


def test_add_questions_with_type_specific_constraints(
    auth_client: ApiClient,
) -> None:
    survey = create_survey(auth_client)
    survey_id = survey["id"]

    single_added = add_question(auth_client, survey_id, q_gate())
    assert single_added["question"]["type"] == "single_choice"
    assert len(single_added["question"]["options"]) == 2

    multi_added = add_question(auth_client, survey_id, q_multi())
    assert multi_added["question"]["validation"] == {
        "min_selected": 2,
        "max_selected": 3,
    }

    number_added = add_question(auth_client, survey_id, q_number())
    assert number_added["question"]["validation"] == {
        "integer": True,
        "min": 18,
        "max": 60,
    }

    text_added = add_question(auth_client, survey_id, q_text())
    assert text_added["question"]["validation"]["max_length"] == 500
    assert (
        single_added["revision"]
        < multi_added["revision"]
        < number_added["revision"]
        < text_added["revision"]
    )


def test_jump_logic_skips_branch(
    auth_client: ApiClient, published_survey: dict
) -> None:
    response = submit(
        auth_client,
        published_survey["id"],
        [
            single("o_no_00000001"),
            text("未使用实验环境，走跳过分支"),
        ],
        anonymous=False,
    )
    assert response.status_code == 201, response.text
    assert response.json()["question_path"] == [
        "q_gate_0001",
        "q_text_0004",
    ]


@pytest.mark.parametrize("selected_count", [1, 4])
def test_multi_choice_count_validation(
    auth_client: ApiClient,
    published_survey: dict,
    selected_count: int,
) -> None:
    option_ids = ["o_opt_a_0001", "o_opt_b_0001", "o_opt_c_0001", "o_opt_d_0001"][
        :selected_count
    ]
    response = submit(
        auth_client,
        published_survey["id"],
        [single(), multi(option_ids), number(20)],
        anonymous=False,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "selection_count"

    stats = auth_client.get(f"/api/surveys/{published_survey['id']}/stats")
    assert stats.status_code == 200, stats.text
    assert stats.json()["response_count"] == 0


@pytest.mark.parametrize("value", [17, 61])
def test_number_range_validation(
    auth_client: ApiClient,
    published_survey: dict,
    value: int,
) -> None:
    response = submit(
        auth_client,
        published_survey["id"],
        [
            single(),
            multi(["o_opt_a_0001", "o_opt_b_0001"]),
            number(value),
        ],
        anonymous=False,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "number_out_of_range"

    stats = auth_client.get(f"/api/surveys/{published_survey['id']}/stats")
    assert stats.status_code == 200, stats.text
    assert stats.json()["response_count"] == 0


def test_normal_and_anonymous_submissions(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
) -> None:
    normal = submit(
        auth_client,
        published_survey["id"],
        [
            single(),
            multi(["o_opt_b_0001", "o_opt_c_0001"]),
            number(20),
            text("正常提交"),
        ],
        anonymous=False,
    )
    assert normal.status_code == 201, normal.text
    assert normal.json()["is_anonymous"] is False
    assert len(normal.json()["question_path"]) == 4

    anonymous = submit(
        anon,
        published_survey["id"],
        [
            single(),
            multi(["o_opt_b_0001", "o_opt_c_0001"]),
            number(25),
            text("匿名提交"),
        ],
        anonymous=True,
    )
    assert anonymous.status_code == 201, anonymous.text
    assert anonymous.json()["is_anonymous"] is True
    assert anonymous.json()["response_id"]


def test_statistics_accuracy(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
) -> None:
    survey_id = published_survey["id"]

    branch = submit(
        auth_client,
        survey_id,
        [single("o_no_00000001"), text("branch")],
        anonymous=False,
    )
    assert branch.status_code == 201, branch.text

    normal = submit(
        auth_client,
        survey_id,
        [
            single(),
            multi(["o_opt_b_0001", "o_opt_c_0001"]),
            number(20),
            text("normal"),
        ],
        anonymous=False,
    )
    assert normal.status_code == 201, normal.text

    anonymous = submit(
        anon,
        survey_id,
        [
            single(),
            multi(["o_opt_b_0001", "o_opt_c_0001"]),
            number(25),
            text("anonymous"),
        ],
        anonymous=True,
    )
    assert anonymous.status_code == 201, anonymous.text

    overview_response = auth_client.get(
        f"/api/surveys/{survey_id}/stats"
    )
    assert overview_response.status_code == 200, overview_response.text
    overview = overview_response.json()
    assert overview["response_count"] == 3

    by_id = {item["question_id"]: item for item in overview["questions"]}
    gate = by_id["q_gate_0001"]
    assert gate["answered_count"] == 3
    assert {
        item["option_id"]: item["count"] for item in gate["option_counts"]
    } == {"o_yes_0000001": 2, "o_no_00000001": 1}

    multi_stats = by_id["q_multi_0002"]
    assert multi_stats["answered_count"] == 2
    assert {
        item["option_id"]: item["count"]
        for item in multi_stats["option_counts"]
    } == {
        "o_opt_a_0001": 0,
        "o_opt_b_0001": 2,
        "o_opt_c_0001": 2,
        "o_opt_d_0001": 0,
    }

    number_stats = by_id["q_number_0003"]
    assert number_stats["answered_count"] == 2
    assert number_stats["average"] == 22.5
    assert number_stats["min"] == 20
    assert number_stats["max"] == 25

    text_stats = by_id["q_text_0004"]
    assert text_stats["answered_count"] == 3

    multi_detail = auth_client.get(
        f"/api/surveys/{survey_id}/questions/q_multi_0002/stats"
    )
    assert multi_detail.status_code == 200, multi_detail.text
    assert multi_detail.json()["answered_count"] == 2

    number_detail = auth_client.get(
        f"/api/surveys/{survey_id}/questions/q_number_0003/stats"
    )
    assert number_detail.status_code == 200, number_detail.text
    assert number_detail.json()["average"] == 22.5

    text_detail = auth_client.get(
        f"/api/surveys/{survey_id}/questions/q_text_0004/stats",
        params={"page": 1, "page_size": 2},
    )
    assert text_detail.status_code == 200, text_detail.text
    text_payload = text_detail.json()
    assert text_payload["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "total_pages": 2,
    }
    assert len(text_payload["answers"]) == 2


def test_owner_cannot_see_or_publish_another_users_survey(
    auth_client: ApiClient, other_client: ApiClient
) -> None:
    survey = create_survey(auth_client)
    listing = other_client.get("/api/surveys")
    assert listing.status_code == 200
    assert survey["id"] not in {item["id"] for item in listing.json()}

    detail = other_client.get(f"/api/surveys/{survey['id']}")
    assert detail.status_code == 404

    publish = other_client.post(f"/api/surveys/{survey['id']}/publish")
    assert publish.status_code == 404

    add_response = other_client.post(
        f"/api/surveys/{survey['id']}/questions", json=q_gate()
    )
    assert add_response.status_code == 404, add_response.text


def test_owner_list_contains_only_own_surveys(
    auth_client: ApiClient, other_client: ApiClient
) -> None:
    own = create_survey(auth_client)
    other = create_survey(other_client)

    own_listing = auth_client.get("/api/surveys")
    assert own_listing.status_code == 200
    ids = {item["id"] for item in own_listing.json()}
    assert own["id"] in ids
    assert other["id"] not in ids


def test_publish_is_idempotent(auth_client: ApiClient) -> None:
    survey = create_survey(auth_client)
    for question in (q_gate(), q_multi(), q_number(), q_text()):
        add_question(auth_client, survey["id"], question)

    first = publish_survey(auth_client, survey["id"])
    second_response = auth_client.post(
        f"/api/surveys/{survey['id']}/publish"
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["survey_version_id"] == first["survey_version_id"]
    assert second["version_no"] == 1


def test_close_survey_blocks_submissions(
    auth_client: ApiClient, published_survey: dict
) -> None:
    closed_response = auth_client.post(
        f"/api/surveys/{published_survey['id']}/close"
    )
    assert closed_response.status_code == 200, closed_response.text
    assert closed_response.json()["status"] == "closed"

    response = submit(
        auth_client,
        published_survey["id"],
        [
            single(),
            multi(["o_opt_a_0001", "o_opt_b_0001"]),
            number(20),
        ],
        anonymous=False,
    )
    assert response.status_code == 409, response.text


def test_allow_multiple_responses_false_rejects_second_submission(
    auth_client: ApiClient,
) -> None:
    survey = create_published_survey(
        auth_client, allow_multiple_responses=False
    )
    first = submit(
        auth_client,
        survey["id"],
        [
            single(),
            multi(["o_opt_a_0001", "o_opt_b_0001"]),
            number(20),
        ],
        anonymous=False,
    )
    assert first.status_code == 201, first.text

    second = submit(
        auth_client,
        survey["id"],
        [
            single(),
            multi(["o_opt_a_0001", "o_opt_b_0001"]),
            number(21),
        ],
        anonymous=False,
    )
    assert second.status_code == 409, second.text


def test_public_slug_flow_branching_and_submission(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
) -> None:
    slug = published_survey["slug"]
    public = anon.get(f"/api/public/surveys/{slug}")
    assert public.status_code == 200, public.text
    assert public.json()["requires_login"] is False
    assert public.json()["is_open"] is True

    first = anon.post(
        f"/api/public/surveys/{slug}/next",
        json={"answers": [], "skipped_question_ids": []},
    )
    assert first.status_code == 200, first.text
    assert first.json()["next_question"]["question_id"] == "q_gate_0001"

    branch = anon.post(
        f"/api/public/surveys/{slug}/next",
        json={
            "answers": [single("o_no_00000001")],
            "skipped_question_ids": [],
        },
    )
    assert branch.status_code == 200, branch.text
    branch_body = branch.json()
    assert branch_body["next_question"]["question_id"] == "q_text_0004"
    assert branch_body["path"] == ["q_gate_0001"]

    completed = anon.post(
        f"/api/public/surveys/{slug}/next",
        json={
            "answers": [single("o_no_00000001")],
            "skipped_question_ids": ["q_text_0004"],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed"] is True
    assert completed.json()["next_question"] is None

    submitted = anon.post(
        f"/api/public/surveys/{slug}/responses",
        json={
            "answers": [
                single("o_no_00000001"),
                text("通过公开链接提交"),
            ],
            "is_anonymous": True,
            "submission_token": str(uuid.uuid4()),
        },
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["question_path"] == [
        "q_gate_0001",
        "q_text_0004",
    ]


def test_public_survey_requires_login_when_anonymous_disabled(
    auth_client: ApiClient,
    anon: ApiClient,
) -> None:
    survey = create_published_survey(auth_client, allow_anonymous=False)
    slug = survey["slug"]

    public = anon.get(f"/api/public/surveys/{slug}")
    assert public.status_code == 200, public.text
    assert public.json()["requires_login"] is True

    no_auth_next = anon.post(
        f"/api/public/surveys/{slug}/next",
        json={"answers": [], "skipped_question_ids": []},
    )
    assert no_auth_next.status_code == 401, no_auth_next.text

    no_auth_submit = anon.post(
        f"/api/public/surveys/{slug}/responses",
        json={
            "answers": [single()],
            "is_anonymous": False,
            "submission_token": str(uuid.uuid4()),
        },
    )
    assert no_auth_submit.status_code == 401, no_auth_submit.text

    with_auth = auth_client.post(
        f"/api/public/surveys/{slug}/next",
        json={"answers": [], "skipped_question_ids": []},
    )
    assert with_auth.status_code == 200, with_auth.text


def test_closed_public_survey_is_not_accepting(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
) -> None:
    closed = auth_client.post(
        f"/api/surveys/{published_survey['id']}/close"
    )
    assert closed.status_code == 200, closed.text

    public = anon.get(f"/api/public/surveys/{published_survey['slug']}")
    assert public.status_code == 200, public.text
    assert public.json()["is_open"] is False

    advance = anon.post(
        f"/api/public/surveys/{published_survey['slug']}/next",
        json={"answers": [], "skipped_question_ids": []},
    )
    assert advance.status_code == 409, advance.text


def test_bulk_draft_save_and_revision_conflict(auth_client: ApiClient) -> None:
    survey = create_survey(auth_client)
    survey_id = survey["id"]
    detail = auth_client.get(f"/api/surveys/{survey_id}")
    assert detail.status_code == 200, detail.text
    draft = detail.json()["current_draft"]
    assert draft["revision"] == 1
    assert draft["questions"] == []

    questions = [q_gate(), q_text()]
    saved = auth_client.request(
        "PUT",
        f"/api/surveys/{survey_id}/draft",
        json={"revision": 1, "questions": questions},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert len(saved.json()["questions"]) == 2

    # The editor must use the returned revision; a stale save is rejected.
    stale = auth_client.request(
        "PUT",
        f"/api/surveys/{survey_id}/draft",
        json={"revision": 1, "questions": questions},
    )
    assert stale.status_code == 409, stale.text

    published = publish_survey(auth_client, survey_id)
    assert published["version_no"] == 1


def test_concurrent_anonymous_submissions(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
) -> None:
    slug = published_survey["slug"]

    def send_one(_index: int):
        return requests.post(
            f"{anon.base_url}/api/public/surveys/{slug}/responses",
            json={
                "answers": [single("o_no_00000001")],
                "is_anonymous": True,
                "submission_token": str(uuid.uuid4()),
            },
            timeout=TIMEOUT,
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(send_one, range(30)))
    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses if response.status_code != 201
    ]

    overview = auth_client.get(
        f"/api/surveys/{published_survey['id']}/stats"
    )
    assert overview.status_code == 200, overview.text
    assert overview.json()["response_count"] == 30
    gate = next(
        item for item in overview.json()["questions"]
        if item["question_id"] == "q_gate_0001"
    )
    no_option = next(
        item for item in gate["option_counts"]
        if item["option_id"] == "o_no_00000001"
    )
    assert no_option["count"] == 30


def test_exact_multi_choice_constraint(
    auth_client: ApiClient,
) -> None:
    survey = create_survey(auth_client)
    survey_id = survey["id"]
    add_question(
        auth_client,
        survey_id,
        {
            "question_id": "q_exact_multi_1",
            "type": "multi_choice",
            "title": "必须恰好选择两项",
            "required": True,
            "options": [
                {"option_id": "o_exact_a_001", "label": "A"},
                {"option_id": "o_exact_b_001", "label": "B"},
                {"option_id": "o_exact_c_001", "label": "C"},
            ],
            "validation": {"exact_selected": 2},
        },
    )
    publish_survey(auth_client, survey_id)

    too_few = submit(
        auth_client,
        survey_id,
        [
            {
                "question_id": "q_exact_multi_1",
                "type": "multi_choice",
                "option_ids": ["o_exact_a_001"],
            }
        ],
        anonymous=False,
    )
    assert too_few.status_code == 422, too_few.text
    assert too_few.json()["detail"]["code"] == "selection_count"

    accepted = submit(
        auth_client,
        survey_id,
        [
            {
                "question_id": "q_exact_multi_1",
                "type": "multi_choice",
                "option_ids": ["o_exact_a_001", "o_exact_b_001"],
            }
        ],
        anonymous=False,
    )
    assert accepted.status_code == 201, accepted.text


def test_multi_and_decimal_number_jumps(
    auth_client: ApiClient,
) -> None:
    survey = create_survey(auth_client)
    survey_id = survey["id"]
    questions = [
        {
            "question_id": "q_multi_jump_01",
            "type": "multi_choice",
            "title": "选择会影响分支",
            "required": True,
            "options": [
                {"option_id": "o_jump_a_0001", "label": "A"},
                {"option_id": "o_jump_b_0001", "label": "B"},
                {"option_id": "o_jump_c_0001", "label": "C"},
            ],
            "validation": {"min_selected": 1, "max_selected": 3},
            "logic": {
                "fallback": {"action": "next"},
                "rules": [
                    {
                        "rule_id": "r_multi_jump_1",
                        "when": {
                            "mode": "all",
                            "conditions": [
                                {
                                    "question_id": "q_multi_jump_01",
                                    "operator": "includes_all",
                                    "value": ["o_jump_a_0001", "o_jump_b_0001"],
                                }
                            ],
                        },
                        "then": {
                            "action": "goto",
                            "target_question_id": "q_text_jump_04",
                        },
                    }
                ],
            },
        },
        {
            "question_id": "q_number_jump_2",
            "type": "number",
            "title": "输入一个数字，支持小数",
            "required": True,
            "validation": {"integer": False, "min": 0, "max": 100},
            "logic": {
                "fallback": {"action": "next"},
                "rules": [
                    {
                        "rule_id": "r_number_jump_2",
                        "when": {
                            "mode": "all",
                            "conditions": [
                                {
                                    "question_id": "q_number_jump_2",
                                    "operator": "gt",
                                    "value": 50.5,
                                }
                            ],
                        },
                        "then": {
                            "action": "goto",
                            "target_question_id": "q_text_jump_04",
                        },
                    }
                ],
            },
        },
        {
            "question_id": "q_text_jump_03",
            "type": "text",
            "title": "数字较小时会经过这里",
            "required": False,
            "validation": {"min_length": 0, "max_length": 100, "trim": True},
        },
        {
            "question_id": "q_text_jump_04",
            "type": "text",
            "title": "共同终点",
            "required": False,
            "validation": {"min_length": 0, "max_length": 100, "trim": True},
        },
    ]
    for question in questions:
        add_question(auth_client, survey_id, question)
    publish_survey(auth_client, survey_id)

    multi_skip = submit(
        auth_client,
        survey_id,
        [
            {
                "question_id": "q_multi_jump_01",
                "type": "multi_choice",
                "option_ids": ["o_jump_a_0001", "o_jump_b_0001"],
            }
        ],
        anonymous=False,
    )
    assert multi_skip.status_code == 201, multi_skip.text
    assert multi_skip.json()["question_path"] == [
        "q_multi_jump_01",
        "q_text_jump_04",
    ]

    number_skip = submit(
        auth_client,
        survey_id,
        [
            {
                "question_id": "q_multi_jump_01",
                "type": "multi_choice",
                "option_ids": ["o_jump_a_0001"],
            },
            {
                "question_id": "q_number_jump_2",
                "type": "number",
                "number": 50.75,
            },
        ],
        anonymous=False,
    )
    assert number_skip.status_code == 201, number_skip.text
    assert number_skip.json()["question_path"] == [
        "q_multi_jump_01",
        "q_number_jump_2",
        "q_text_jump_04",
    ]

    normal = submit(
        auth_client,
        survey_id,
        [
            {
                "question_id": "q_multi_jump_01",
                "type": "multi_choice",
                "option_ids": ["o_jump_a_0001"],
            },
            {
                "question_id": "q_number_jump_2",
                "type": "number",
                "number": 20.25,
            },
        ],
        anonymous=False,
    )
    assert normal.status_code == 201, normal.text
    assert normal.json()["question_path"] == [
        "q_multi_jump_01",
        "q_number_jump_2",
        "q_text_jump_03",
        "q_text_jump_04",
    ]

    overview = auth_client.get(f"/api/surveys/{survey_id}/stats")
    assert overview.status_code == 200, overview.text
    number_stats = next(
        item for item in overview.json()["questions"]
        if item["question_id"] == "q_number_jump_2"
    )
    assert number_stats["answered_count"] == 2
    assert number_stats["average"] == 35.5
    assert number_stats["min"] == 20.25
    assert number_stats["max"] == 50.75


def test_published_operational_settings_can_change(
    auth_client: ApiClient, anon: ApiClient, published_survey: dict
) -> None:
    response = auth_client.patch(
        f"/api/surveys/{published_survey['id']}",
        json={
            "title": "更新后的标题",
            "allow_anonymous": False,
            "allow_multiple_responses": False,
            "closes_at": "2027-06-30T12:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "更新后的标题"
    assert body["allow_anonymous"] is False
    assert body["allow_multiple_responses"] is False

    public = anon.get(f"/api/public/surveys/{published_survey['slug']}")
    assert public.status_code == 200, public.text
    assert public.json()["requires_login"] is True
    assert public.json()["allow_multiple_responses"] is False


def test_new_version_clone_publish_and_response_preservation(
    auth_client: ApiClient,
    anon: ApiClient,
    published_survey: dict,
    mongo_uri: str,
    test_database_name: str,
) -> None:
    survey_id = published_survey["id"]
    original_version_id = published_survey["survey_version_id"]

    first_response = submit(
        auth_client,
        survey_id,
        [single("o_no_00000001")],
        anonymous=False,
    )
    assert first_response.status_code == 201, first_response.text

    new_draft_response = auth_client.post(
        f"/api/surveys/{survey_id}/new-draft"
    )
    assert new_draft_response.status_code == 200, new_draft_response.text
    new_draft = new_draft_response.json()
    assert new_draft["version_no"] == 2
    assert new_draft["state"] == "draft"
    assert len(new_draft["questions"]) == 4

    # Repeated call is idempotent and returns the same open draft.
    again = auth_client.post(f"/api/surveys/{survey_id}/new-draft")
    assert again.status_code == 200
    assert again.json()["id"] == new_draft["id"]

    questions = new_draft["questions"]
    questions[0]["title"] = "新版本中的第一题"
    saved = auth_client.request(
        "PUT",
        f"/api/surveys/{survey_id}/draft",
        json={"revision": 1, "questions": questions},
    )
    assert saved.status_code == 200, saved.text

    published = auth_client.post(f"/api/surveys/{survey_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["version_no"] == 2

    detail = auth_client.get(f"/api/surveys/{survey_id}")
    assert detail.status_code == 200
    assert detail.json()["current_draft"] is None
    assert detail.json()["published_version"]["version_no"] == 2
    assert detail.json()["published_version"]["questions"][0]["title"] == "新版本中的第一题"

    # The old response is retained against version 1.
    sync = MongoClient(mongo_uri)
    try:
        responses = sync[test_database_name]["responses"]
        assert responses.count_documents(
            {
                "survey_id": ObjectId(survey_id),
                "survey_version_id": ObjectId(original_version_id),
            }
        ) == 1
    finally:
        sync.close()

    # Current-version statistics correctly do not mix v1 responses into v2.
    overview = auth_client.get(f"/api/surveys/{survey_id}/stats")
    assert overview.status_code == 200
    assert overview.json()["version"]["version_no"] == 2
    assert overview.json()["response_count"] == 0

    anonymous = submit(
        anon,
        survey_id,
        [single("o_no_00000001")],
        anonymous=True,
    )
    assert anonymous.status_code == 201, anonymous.text
    overview = auth_client.get(f"/api/surveys/{survey_id}/stats")
    assert overview.json()["response_count"] == 1


def test_web_pages_and_static_assets(
    auth_client: ApiClient,
    other_client: ApiClient,
    anon: ApiClient,
) -> None:
    assert requests.get(f"{anon.base_url}/login", timeout=TIMEOUT).status_code == 200
    assert requests.get(f"{anon.base_url}/register", timeout=TIMEOUT).status_code == 200
    assert requests.get(f"{anon.base_url}/static/css/app.css", timeout=TIMEOUT).status_code == 200

    redirect = anon.get("/dashboard", allow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"].startswith("/login?next=")

    dashboard = auth_client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "创建问卷" in dashboard.text

    survey = create_survey(auth_client)
    editor = auth_client.get(f"/surveys/{survey['id']}/edit")
    assert editor.status_code == 200
    assert "问卷编辑器" in editor.text

    forbidden_page = other_client.get(f"/surveys/{survey['id']}/edit")
    assert forbidden_page.status_code == 404

    add_question(auth_client, survey["id"], q_gate())
    add_question(auth_client, survey["id"], q_text())
    publish_survey(auth_client, survey["id"])

    public_page = anon.get(f"/survey/{survey['slug']}")
    assert public_page.status_code == 200
    assert "正在加载问卷" in public_page.text

    stats_page = auth_client.get(f"/surveys/{survey['id']}/stats")
    assert stats_page.status_code == 200
    assert "问卷统计" in stats_page.text or "正在读取统计结果" in stats_page.text
