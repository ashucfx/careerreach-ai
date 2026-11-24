import asyncio
import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from careerreach.config import get_settings
from careerreach.job_intelligence import JobIntelligenceService, JobNotFound
from careerreach.migrations import migrate
from careerreach.models import ModelResponse
from careerreach.schemas import (
    CompanyEvidenceQuote,
    CompanyResearchAnalysis,
    CompanyResearchFinding,
    CompanyResearchRequest,
    JobAnalysis,
    JobRequirement,
    JobSubmission,
    WebResearchResponse,
    WebResearchResult,
)
from psycopg import AsyncConnection


class FakeModelRouter:
    async def complete(self, task: str, system: str, prompt: str, schema: type):
        if schema is JobAnalysis:
            value = JobAnalysis(
                role_summary="Build Python services.",
                summary_quotes=["build reliable Python services"],
                requirements=[
                    JobRequirement(
                        requirement="Python experience",
                        category="skill",
                        required=True,
                        source_quote="5+ years of Python experience",
                    )
                ],
            )
        else:
            value = CompanyResearchAnalysis(
                summary="The company makes cloud software.",
                summary_quotes=[
                    CompanyEvidenceQuote(
                        evidence_id="brave:company-source",
                        quote="We build cloud software for teams.",
                    )
                ],
                findings=[
                    CompanyResearchFinding(
                        category="product",
                        claim="The company makes cloud software.",
                        source_quotes=[
                            CompanyEvidenceQuote(
                                evidence_id="brave:company-source",
                                quote="We build cloud software for teams.",
                            )
                        ],
                    )
                ],
            )
        return ModelResponse(
            value=value,
            model="integration-test-model",
            latency_ms=4,
            input_tokens=10,
            output_tokens=12,
        )


class FakeSearchProvider:
    configured = True

    async def search(self, query: str, count: int) -> WebResearchResponse:
        captured_at = datetime.now(UTC)
        return WebResearchResponse(
            query=query,
            captured_at=captured_at,
            results=[
                WebResearchResult(
                    id="brave:company-source",
                    title="Example company products",
                    url="https://example.org/products",
                    snippet="We build cloud software for teams.",
                    captured_at=captured_at,
                )
            ][:count],
        )


@pytest.fixture(autouse=True)
def prepare_database(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    database_url = os.environ.get("CAREERREACH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("CAREERREACH_TEST_DATABASE_URL is required for PostgreSQL integration tests.")
    monkeypatch.setenv("CAREERREACH_DATABASE_URL", database_url)
    monkeypatch.setenv("CAREERREACH_MIGRATION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    asyncio.run(migrate())
    yield
    get_settings.cache_clear()


async def _create_test_user(database_url: str) -> UUID:
    user_id = uuid4()
    async with await AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            "INSERT INTO app_user (id, email, password_hash) VALUES (%s, %s, %s)",
            (user_id, f"job-test-{user_id.hex}@example.org", "not-used-by-this-test"),
        )
        await connection.commit()
    return user_id


def test_job_analysis_versions_and_storage_are_tenant_scoped() -> None:
    settings = get_settings()
    service = JobIntelligenceService(settings, FakeModelRouter(), FakeSearchProvider())
    primary_user = asyncio.run(_create_test_user(settings.database_url or ""))
    other_user = asyncio.run(_create_test_user(settings.database_url or ""))
    submission = JobSubmission(
        title="Backend Engineer",
        company_name="Example Corp",
        location="Remote",
        source_url="https://jobs.example.org/backend",
        description=(
            "We are hiring a backend engineer to build reliable Python services. "
            "Required: 5+ years of Python experience. The team works across multiple systems."
        ),
    )

    first = asyncio.run(service.analyze_job(primary_user, submission))
    second = asyncio.run(service.analyze_job(primary_user, submission))
    assert first.id == second.id
    assert second.version == 2
    assert second.analysis.requirements[0].source_quote == "5+ years of Python experience"
    assert len(asyncio.run(service.list_jobs(primary_user))) == 1
    assert asyncio.run(service.list_jobs(other_user)) == []
    with pytest.raises(JobNotFound):
        asyncio.run(service.get_job(other_user, first.id))

    asyncio.run(service.delete_job(primary_user, first.id))
    assert asyncio.run(service.list_jobs(primary_user)) == []


def test_company_research_versions_preserve_sources_and_isolate_tenants() -> None:
    settings = get_settings()
    service = JobIntelligenceService(settings, FakeModelRouter(), FakeSearchProvider())
    primary_user = asyncio.run(_create_test_user(settings.database_url or ""))
    other_user = asyncio.run(_create_test_user(settings.database_url or ""))
    request = CompanyResearchRequest(company_name="Example Corp", result_count=4)

    first = asyncio.run(service.research_company(primary_user, request))
    second = asyncio.run(service.research_company(primary_user, request))
    assert first.company_id == second.company_id
    assert second.version == 2
    assert second.sources[0].url == "https://example.org/products"
    assert second.analysis.findings[0].source_quotes[0].quote in second.sources[0].snippet
    summaries = asyncio.run(service.list_company_research(primary_user))
    assert len(summaries) == 1
    assert summaries[0].latest_version == 2
    assert asyncio.run(service.list_company_research(other_user)) == []
