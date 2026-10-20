"""Authentication API tests against the live test server."""

from __future__ import annotations

import uuid

import requests

TIMEOUT = 15


def _credentials(prefix: str = "auth") -> dict:
    suffix = uuid.uuid4().hex[:10]
    username = f"{prefix}_{suffix}"[:32]
    return {
        "username": username,
        "email": f"{username}@example.com",
        "password": "StrongPass123!",
        "display_name": "认证测试用户",
    }


def test_register_me_logout_and_login(api_base_url: str) -> None:
    session = requests.Session()
    payload = _credentials()
    register = session.post(
        f"{api_base_url}/api/auth/register",
        json=payload,
        timeout=TIMEOUT,
    )
    assert register.status_code == 201, register.text
    body = register.json()
    assert body["user"]["username"] == payload["username"]
    assert body["user"]["email"] == payload["email"]
    assert body["access_token"]
    assert session.cookies.get("survey_access_token")

    me = session.get(f"{api_base_url}/api/auth/me", timeout=TIMEOUT)
    assert me.status_code == 200, me.text
    assert me.json()["id"] == body["user"]["id"]

    logout = session.post(f"{api_base_url}/api/auth/logout", timeout=TIMEOUT)
    assert logout.status_code == 204, logout.text

    after_logout = session.get(f"{api_base_url}/api/auth/me", timeout=TIMEOUT)
    assert after_logout.status_code == 401

    wrong = session.post(
        f"{api_base_url}/api/auth/login",
        json={
            "username": payload["username"],
            "password": "WrongPassword123!",
        },
        timeout=TIMEOUT,
    )
    assert wrong.status_code == 401

    login = session.post(
        f"{api_base_url}/api/auth/login",
        json={
            "username": payload["username"].upper(),
            "password": payload["password"],
        },
        timeout=TIMEOUT,
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = session.get(f"{api_base_url}/api/auth/me", timeout=TIMEOUT)
    assert me.status_code == 200

    bearer = requests.get(
        f"{api_base_url}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    assert bearer.status_code == 200
    session.close()


def test_duplicate_username_and_email_are_rejected(api_base_url: str) -> None:
    payload = _credentials("dup")
    first = requests.post(
        f"{api_base_url}/api/auth/register",
        json=payload,
        timeout=TIMEOUT,
    )
    assert first.status_code == 201

    same_username = dict(payload)
    same_username["email"] = f"another_{uuid.uuid4().hex[:8]}@example.com"
    response = requests.post(
        f"{api_base_url}/api/auth/register",
        json=same_username,
        timeout=TIMEOUT,
    )
    assert response.status_code == 409, response.text

    same_email = dict(payload)
    same_email["username"] = f"other_{uuid.uuid4().hex[:10]}"
    response = requests.post(
        f"{api_base_url}/api/auth/register",
        json=same_email,
        timeout=TIMEOUT,
    )
    assert response.status_code == 409, response.text


def test_protected_survey_list_requires_authentication(api_base_url: str) -> None:
    response = requests.get(
        f"{api_base_url}/api/surveys",
        timeout=TIMEOUT,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "authentication required"


def test_invalid_bearer_token_is_rejected(api_base_url: str) -> None:
    response = requests.get(
        f"{api_base_url}/api/surveys",
        headers={"Authorization": "Bearer invalid-token"},
        timeout=TIMEOUT,
    )
    assert response.status_code == 401
