import asyncio
import os
from collections.abc import Generator
from uuid import uuid4

import pytest
from careerreach.config import get_settings
from careerreach.main import app
from careerreach.migrations import migrate
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def prepare_database(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    database_url = os.environ.get("CAREERREACH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("CAREERREACH_TEST_DATABASE_URL is required for PostgreSQL integration tests.")
    monkeypatch.setenv("CAREERREACH_DATABASE_URL", database_url)
    get_settings.cache_clear()
    asyncio.run(migrate())
    asyncio.run(migrate())
    yield
    get_settings.cache_clear()


def test_registration_login_and_session_revocation() -> None:
    email = f"candidate-{uuid4().hex}@example.org"
    password = "a-long-test-password-ensuring-strength"
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert registration.status_code == 201
        identity = registration.json()
        assert identity["email"] == email

        duplicate = client.post(
            "/api/v1/auth/register", json={"email": email.swapcase(), "password": password}
        )
        assert duplicate.status_code == 409

        failed_login = client.post(
            "/api/v1/auth/token", json={"email": email, "password": "incorrect-password"}
        )
        assert failed_login.status_code == 401

        login = client.post(
            "/api/v1/auth/token", json={"email": email.swapcase(), "password": password}
        )
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        current_user = client.get("/api/v1/auth/me", headers=headers)
        assert current_user.status_code == 200
        assert current_user.json()["id"] == identity["id"]

        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 204
        revoked = client.get("/api/v1/auth/me", headers=headers)
        assert revoked.status_code == 401
