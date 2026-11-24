import asyncio
import io
import os
import zipfile
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from careerreach.config import get_settings
from careerreach.main import app
from careerreach.migrations import migrate
from careerreach.models import ModelResponse
from careerreach.resume_parser import DOCX_CONTENT_TYPE
from careerreach.schemas import ResumeExtraction, ResumeFact, ResumeSkillFact
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
    email = f"resume-{uuid4().hex}@example.org"
    password = "a-long-test-password-ensuring-strength"
    registration = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert registration.status_code == 201
    token = client.post("/api/v1/auth/token", json={"email": email, "password": password})
    assert token.status_code == 200
    return registration.json()["id"], token.json()["access_token"]


def _docx(text: str) -> bytes:
    xml_text = "".join(f"<w:t>{part} </w:t>" for part in text.split(" "))
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p>{xml_text}</w:p></w:body></w:document>"
    )
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


class FakeModelRouter:
    async def complete(
        self, task: str, system: str, prompt: str, schema: type[ResumeExtraction]
    ) -> ModelResponse:
        assert task == "extraction"
        assert "untrusted data" in system
        assert "Ashu Shukla" in prompt
        return ModelResponse(
            value=ResumeExtraction(
                full_name=ResumeFact(value="Ashu Shukla", source_quote="Ashu Shukla"),
                skills=[ResumeSkillFact(name="Python", source_quote="Python, FastAPI")],
            ),
            model="integration-test-extractor",
            latency_ms=7,
            input_tokens=12,
            output_tokens=15,
        )


def test_resume_ingestion_extraction_and_tenant_isolation() -> None:
    with TestClient(app) as client:
        user_id, token = _create_account(client)
        headers = {"Authorization": f"Bearer {token}"}
        document = _docx("Ashu Shukla Python, FastAPI")
        client.app.state.resume_service._models = FakeModelRouter()

        uploaded = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={
                "file": (
                    "candidate.docx",
                    document,
                    DOCX_CONTENT_TYPE,
                )
            },
        )
        assert uploaded.status_code == 201
        uploaded_data = uploaded.json()
        resume_id = uploaded_data["id"]
        assert uploaded_data["extracted_text"] == "Ashu Shukla Python, FastAPI"
        assert uploaded_data["extraction"] is None

        repeated_upload = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={"file": ("duplicate.docx", document, DOCX_CONTENT_TYPE)},
        )
        assert repeated_upload.status_code == 201
        assert repeated_upload.json()["id"] == resume_id

        extracted = client.post(f"/api/v1/resumes/{resume_id}/extract", headers=headers)
        assert extracted.status_code == 200
        assert extracted.json()["extraction_version"] == 1
        assert extracted.json()["extraction_model"] == "integration-test-extractor"
        assert extracted.json()["extraction"]["skills"][0]["name"] == "Python"
        listed = client.get("/api/v1/resumes", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["sha256"] == uploaded_data["sha256"]

        async def read_without_tenant() -> tuple[list[tuple[UUID]], list[tuple[UUID]]]:
            async with await AsyncConnection.connect(
                os.environ["CAREERREACH_TEST_DATABASE_URL"]
            ) as connection:
                cursor = await connection.execute("SELECT id FROM resume_document")
                documents = await cursor.fetchall()
                cursor = await connection.execute("SELECT id FROM resume_extraction")
                extractions = await cursor.fetchall()
                return documents, extractions

        assert asyncio.run(read_without_tenant()) == ([], [])

        other_user_id, other_token = _create_account(client)
        assert other_user_id != user_id
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert client.get("/api/v1/resumes", headers=other_headers).json() == []
        assert client.get(f"/api/v1/resumes/{resume_id}", headers=other_headers).status_code == 404

        too_large = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={"file": ("large.docx", b"x" * (6 * 1024 * 1024), DOCX_CONTENT_TYPE)},
        )
        assert too_large.status_code == 413

        assert client.delete(f"/api/v1/resumes/{resume_id}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/resumes/{resume_id}", headers=headers).status_code == 404
