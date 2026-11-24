from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .schemas import WebResearchResponse, WebResearchResult

_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class SearchNotConfigured(RuntimeError):
    pass


class SearchProviderError(RuntimeError):
    pass


class BraveSearchProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    @property
    def configured(self) -> bool:
        return self._settings.brave_search_api_key is not None

    async def search(self, query: str, count: int) -> WebResearchResponse:
        api_key = self._settings.brave_search_api_key
        if api_key is None:
            raise SearchNotConfigured(
                "Set CAREERREACH_BRAVE_SEARCH_API_KEY to enable web research."
            )
        try:
            response = await self._client.get(
                _BRAVE_SEARCH_ENDPOINT,
                params={"q": query, "count": count, "safesearch": "moderate"},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key.get_secret_value(),
                },
                timeout=15.0,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("The web search provider request failed.") from exc

        if not isinstance(body, dict):
            raise SearchProviderError("The web search provider returned an invalid response.")
        parsed_body = cast(dict[str, object], body)
        web = parsed_body.get("web")
        raw_results: list[object] = []
        if isinstance(web, dict):
            web_data = cast(dict[str, object], web)
            candidate_results = web_data.get("results", [])
            if not isinstance(candidate_results, list):
                raise SearchProviderError("The web search provider returned malformed results.")
            raw_results = cast(list[object], candidate_results)
        elif web is not None:
            raise SearchProviderError("The web search provider returned malformed results.")

        captured_at = datetime.now(UTC)
        results: list[WebResearchResult] = []
        for item in raw_results[:count]:
            if not isinstance(item, dict):
                continue
            result_data = cast(dict[str, object], item)
            title = result_data.get("title")
            url = result_data.get("url")
            snippet = result_data.get("description")
            if (
                not isinstance(title, str)
                or not title.strip()
                or not isinstance(url, str)
                or not url.strip()
                or not isinstance(snippet, str)
                or not snippet.strip()
            ):
                continue
            title = title.strip()
            url = url.strip()
            snippet = snippet.strip()
            try:
                parsed_url = urlsplit(url)
                hostname = parsed_url.hostname
            except ValueError:
                continue
            if (
                parsed_url.scheme not in {"http", "https"}
                or hostname is None
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                continue
            source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            results.append(
                WebResearchResult(
                    id=f"brave:{source_id}",
                    title=title.strip()[:500],
                    url=url[:2_000],
                    snippet=snippet.strip()[:4_000],
                    captured_at=captured_at,
                )
            )
        return WebResearchResponse(query=query, results=results, captured_at=captured_at)

    async def test_connection(self) -> WebResearchResponse:
        return await self.search("site:brave.com Brave Search", count=1)
