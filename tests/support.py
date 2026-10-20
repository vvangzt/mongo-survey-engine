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


__all__ = ["ApiClient", "anonymous_client", "register_client"]
