"""Small HTTP helper shared by API test modules."""

from __future__ import annotations

import uuid
from typing import Any

import requests

DEFAULT_TIMEOUT = 15


class ApiClient:
    def __init__(
        self, base_url: str, session: requests.Session | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        return self.session.request(
            method, f"{self.base_url}{path}", **kwargs
        )

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self.session.close()


def register_client(
    base_url: str, *, prefix: str = "user"
) -> tuple[ApiClient, dict[str, Any]]:
    client = ApiClient(base_url)
    suffix = uuid.uuid4().hex[:10]
    username = f"{prefix}_{suffix}"[:32]
    payload = {
        "username": username,
        "email": f"{username}@example.com",
        "password": "StrongPass123!",
        "display_name": f"用户 {suffix[:4]}",
    }
    response = client.post("/api/auth/register", json=payload)
    if response.status_code != 201:
        client.close()
        raise AssertionError(
            f"registration failed: {response.status_code} {response.text}"
        )
    return client, response.json()["user"]


def anonymous_client(base_url: str) -> ApiClient:
    return ApiClient(base_url)


# ---------------------------------------------------------------------------
# phase 2 helpers: question library payloads
# ---------------------------------------------------------------------------


def option_pairs(*labels: str) -> list[dict[str, str]]:
    return [
        {"option_id": f"o_opt_{index:08d}", "label": label}
        for index, label in enumerate(labels)
    ]


def single_choice_content(
    title: str = "你的身份是？", labels: tuple[str, ...] = ("学生", "教师")
) -> dict[str, Any]:
    return {
        "type": "single_choice",
        "title": title,
        "required": True,
        "options": option_pairs(*labels),
    }


def multi_choice_content(
    title: str = "你使用过哪些课程资源？",
    labels: tuple[str, ...] = ("课件", "录播视频", "实验环境"),
) -> dict[str, Any]:
    return {
        "type": "multi_choice",
        "title": title,
        "required": False,
        "options": option_pairs(*labels),
        "validation": {"min_selected": 1, "max_selected": len(labels)},
    }


def number_content(
    title: str = "年龄（周岁）",
    *,
    required: bool = True,
    minimum: int = 0,
    maximum: int = 120,
) -> dict[str, Any]:
    return {
        "type": "number",
        "title": title,
        "required": required,
        "validation": {"integer": True, "min": minimum, "max": maximum},
    }


def text_content(title: str = "补充建议") -> dict[str, Any]:
    return {
        "type": "text",
        "title": title,
        "required": False,
        "validation": {"min_length": 0, "max_length": 500, "trim": True},
    }


def create_question(
    client: ApiClient,
    content: dict[str, Any],
    *,
    visibility: str = "private",
) -> dict[str, Any]:
    response = client.post(
        "/api/questions",
        json={"content": content, "visibility": visibility},
    )
    if response.status_code != 201:
        raise AssertionError(
            f"create question failed: {response.status_code} {response.text}"
        )
    return response.json()


def create_survey(
    client: ApiClient,
    title: str,
    *,
    allow_anonymous: bool = True,
) -> dict[str, Any]:
    response = client.post(
        "/api/surveys",
        json={
            "title": title,
            "allow_anonymous": allow_anonymous,
            "allow_multiple_responses": True,
        },
    )
    if response.status_code != 201:
        raise AssertionError(
            f"create survey failed: {response.status_code} {response.text}"
        )
    return response.json()


def add_from_library(
    client: ApiClient, survey_id: str, question_version_id: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/surveys/{survey_id}/questions/from-library",
        json={"question_version_id": question_version_id},
    )
    if response.status_code != 201:
        raise AssertionError(
            f"add from library failed: {response.status_code} {response.text}"
        )
    return response.json()


def publish(client: ApiClient, survey_id: str) -> dict[str, Any]:
    response = client.post(f"/api/surveys/{survey_id}/publish")
    if response.status_code != 200:
        raise AssertionError(
            f"publish failed: {response.status_code} {response.text}"
        )
    return response.json()


def submit_answer(
    client: ApiClient,
    slug: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        f"/api/public/surveys/{slug}/responses",
        json={
            "answers": answers,
            "is_anonymous": True,
            "submission_token": uuid.uuid4().hex,
        },
    )
    if response.status_code != 201:
        raise AssertionError(
            f"submit failed: {response.status_code} {response.text}"
        )
    return response.json()


def whoami(client: ApiClient) -> dict[str, Any]:
    response = client.get("/api/auth/me")
    if response.status_code != 200:
        raise AssertionError(f"whoami failed: {response.status_code}")
    return response.json()


__all__ = [
    "ApiClient",
    "add_from_library",
    "anonymous_client",
    "create_question",
    "create_survey",
    "multi_choice_content",
    "number_content",
    "option_pairs",
    "publish",
    "register_client",
    "single_choice_content",
    "submit_answer",
    "text_content",
    "whoami",
]
