"""Pytest fixtures: isolated MongoDB and a live Uvicorn server.

Tests use the real registration/login flow and real cookie authentication.
No test-only authentication dependency overrides are installed.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import ApiClient, anonymous_client, register_client  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_mongo(uri: str, timeout: float = 15.0) -> None:
    client = MongoClient(uri, serverSelectionTimeoutMS=250)
    deadline = time.time() + timeout
    last_error: Exception | None = None
    try:
        while time.time() < deadline:
            try:
                client.admin.command("ping")
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"MongoDB did not start at {uri}") from last_error
    finally:
        client.close()


@pytest.fixture(scope="session")
def mongo_uri() -> str:
    external_uri = os.getenv("MONGODB_TEST_URI")
    if external_uri:
        _wait_for_mongo(external_uri)
        yield external_uri
        return

    mongod = shutil.which("mongod")
    if not mongod:
        pytest.skip(
            "mongod not found; set MONGODB_TEST_URI to a disposable MongoDB"
        )

    dbpath = Path(tempfile.mkdtemp(prefix="survey-api-mongo-"))
    port = _free_port()
    uri = f"mongodb://127.0.0.1:{port}"
    logpath = dbpath / "mongod.log"
    process = subprocess.Popen(
        [
            mongod,
            "--dbpath",
            str(dbpath),
            "--port",
            str(port),
            "--bind_ip",
            "127.0.0.1",
            "--logpath",
            str(logpath),
            "--logappend",
            "--quiet",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_mongo(uri)
        yield uri
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        shutil.rmtree(dbpath, ignore_errors=True)


@pytest.fixture(scope="session")
def test_database_name() -> str:
    return f"survey_api_it_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def api_base_url(mongo_uri: str, test_database_name: str) -> str:
    os.environ["MONGODB_URI"] = mongo_uri
    os.environ["MONGODB_DB"] = test_database_name
    os.environ["JWT_SECRET"] = f"test-secret-{uuid.uuid4().hex}"
    os.environ["AUTO_CREATE_INDEXES"] = "true"

    import uvicorn

    from backend.main import app

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        if server.started:
            try:
                response = requests.get(f"{base_url}/openapi.json", timeout=0.5)
                if response.status_code == 200:
                    ready = True
                    break
            except requests.RequestException:
                pass
        time.sleep(0.05)
    if not ready:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("test HTTP server did not start")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)

        client = MongoClient(mongo_uri)
        try:
            client.drop_database(test_database_name)
        finally:
            client.close()


@pytest.fixture
def auth_client(api_base_url: str):
    client, _user = register_client(api_base_url, prefix="owner")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def other_client(api_base_url: str):
    client, _user = register_client(api_base_url, prefix="other")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def anon(api_base_url: str):
    client = anonymous_client(api_base_url)
    try:
        yield client
    finally:
        client.close()
