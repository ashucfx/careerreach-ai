import asyncio
import os
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from careerreach.config import get_settings
from careerreach.main import app
from careerreach.migrations import migrate
from fastapi.testclient import TestClient
from psycopg import AsyncConnection


@pytest.fixture(autouse=True)
def prepare_database(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    database_url = os.environ.get("CAREERREACH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("CAREERREACH_TEST_DATABASE_URL is required for PostgreSQL integration tests.")
    monkeypatch.setenv("CAREERREACH_DATABASE_URL", database_url)
    get_settings.cache_clear()
    asyncio.run(migrate())
    yield
    get_settings.cache_clear()


def _create_account(client: TestClient) -> tuple[str, str]:
    email = f"candidate-{uuid4().hex}@example.org"
    password = "a-long-test-password-ensuring-strength"
    registration = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert registration.status_code == 201
    token = client.post("/api/v1/auth/token", json={"email": email, "password": password})
    assert token.status_code == 200
    return registration.json()["id"], token.json()["access_token"]


def test_candidate_profile_is_versioned_and_isolated_by_row_security() -> None:
    with TestClient(app) as client:
        user_id, token = _create_account(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/profile", headers=headers).status_code == 404

        created = client.put(
            "/api/v1/profile",
            headers=headers,
            json={
                "full_name": "Candidate One",
                "headline": "Backend engineer",
                "target_titles": ["Backend Engineer"],
                "target_locations": ["Berlin"],
                "skills": [{"name": "Python", "proficiency": "advanced", "years_experience": 6}],
                "experiences": [
                    {
                        "employer": "Example Systems",
                        "title": "Backend Engineer",
                        "location": "Berlin",
                        "description": "Built distributed services.",
                        "start_date": "2021-01-01T00:00:00Z",
                        "currently_employed": True,
                    }
                ],
                "education": [
                    {
                        "institution": "Example University",
                        "credential": "BSc",
                        "field_of_study": "Computer Science",
                        "start_year": 2014,
                        "end_year": 2018,
                    }
                ],
            },
        )
        assert created.status_code == 200
        assert created.json()["version"] == 1
        assert created.json()["skills"][0]["name"] == "Python"

        async def read_without_tenant() -> list[tuple[UUID]]:
            async with await AsyncConnection.connect(
                os.environ["CAREERREACH_TEST_DATABASE_URL"]
            ) as connection:
                cursor = await connection.execute("SELECT id FROM candidate_profile")
                return await cursor.fetchall()

        assert asyncio.run(read_without_tenant()) == []

        updated = client.put(
            "/api/v1/profile",
            headers=headers,
            json={
                "expected_version": 1,
                "full_name": "Candidate One",
                "headline": "Senior backend engineer",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        assert updated.json()["skills"] == []
        history = client.get("/api/v1/profile/history", headers=headers)
        assert history.status_code == 200
        assert len(history.json()) == 1
        assert history.json()[0]["version"] == 1
        assert history.json()[0]["snapshot"]["skills"][0]["name"] == "Python"

        stale = client.put(
            "/api/v1/profile",
            headers=headers,
            json={"expected_version": 1, "full_name": "Stale write"},
        )
        assert stale.status_code == 409

        other_user_id, other_token = _create_account(client)
        assert other_user_id != user_id
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert client.get("/api/v1/profile", headers=other_headers).status_code == 404

        assert client.delete("/api/v1/profile", headers=headers).status_code == 204
        assert client.get("/api/v1/profile", headers=headers).status_code == 404
