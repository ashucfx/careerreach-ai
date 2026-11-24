import httpx
import pytest
from careerreach.config import Settings
from careerreach.web_research import BraveSearchProvider, SearchNotConfigured, SearchProviderError
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_brave_search_returns_timestamped_http_sources_and_discards_invalid_urls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.search.brave.com"
        assert request.url.params["q"] == "backend engineer jobs"
        assert request.url.params["count"] == "5"
        assert request.headers["X-Subscription-Token"] == "test-token"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Backend engineer role",
                            "url": "https://jobs.example.org/backend",
                            "description": "The role builds resilient Python services.",
                        },
                        {
                            "title": "Unsafe result",
                            "url": "javascript:alert(1)",
                            "description": "This URL must not be returned.",
                        },
                    ]
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BraveSearchProvider(Settings(brave_search_api_key=SecretStr("test-token")), client)
    result = await provider.search("backend engineer jobs", count=5)
    await client.aclose()

    assert len(result.results) == 1
    assert result.results[0].url == "https://jobs.example.org/backend"
    assert result.results[0].captured_at.tzinfo is not None


@pytest.mark.asyncio
async def test_brave_search_requires_a_real_api_key() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("no request")))
    provider = BraveSearchProvider(Settings(), client)
    with pytest.raises(SearchNotConfigured, match="CAREERREACH_BRAVE_SEARCH_API_KEY"):
        await provider.search("company research", count=3)
    await client.aclose()


@pytest.mark.asyncio
async def test_brave_search_does_not_expose_provider_error_details_or_credentials() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="test-token is invalid")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BraveSearchProvider(Settings(brave_search_api_key=SecretStr("test-token")), client)
    with pytest.raises(SearchProviderError) as error:
        await provider.search("company research", count=3)
    await client.aclose()
    assert "test-token" not in str(error.value)
