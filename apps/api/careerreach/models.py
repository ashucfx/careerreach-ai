from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings


class ModelGatewayError(RuntimeError):
    pass


class ModelConfigurationError(ModelGatewayError):
    pass


class ModelProviderError(ModelGatewayError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    value: BaseModel
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


class ModelProvider(Protocol):
    async def generate(
        self, task: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> ModelResponse: ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def model_for(self, task: str) -> str:
        models = {
            "reasoning": self._settings.reasoning_model,
            "communication": self._settings.communication_model,
            "extraction": self._settings.extraction_model,
        }
        if task not in models:
            raise ModelConfigurationError(f"No model route is configured for task '{task}'.")
        return models[task]

    async def generate(
        self, task: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> ModelResponse:
        if self._settings.model_api_key is None:
            raise ModelConfigurationError(
                "Set CAREERREACH_MODEL_API_KEY to enable model workflows."
            )
        model = self.model_for(task)
        candidates = [model]
        if self._settings.model_fallback and self._settings.model_fallback != model:
            candidates.append(self._settings.model_fallback)
        last_error: Exception | None = None
        for candidate in candidates:
            for attempt in range(self._settings.model_max_retries + 1):
                started = time.perf_counter()
                try:
                    response = await self._client.post(
                        f"{self._settings.model_base_url.rstrip('/')}/chat/completions",
                        headers={
                            "Authorization": (
                                f"Bearer {self._settings.model_api_key.get_secret_value()}"
                            )
                        },
                        json={
                            "model": candidate,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": prompt},
                            ],
                            "response_format": {"type": "json_object"},
                        },
                        timeout=self._settings.model_timeout_seconds,
                    )
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    value = schema.model_validate_json(content)
                    usage = body.get("usage", {})
                    return ModelResponse(
                        value=value,
                        model=candidate,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                    )
                except (
                    httpx.HTTPError,
                    KeyError,
                    IndexError,
                    TypeError,
                    ValueError,
                    ValidationError,
                ) as exc:
                    last_error = exc
                    if attempt < self._settings.model_max_retries:
                        await asyncio.sleep(min(0.25 * 2**attempt, 2))
            if candidate != candidates[-1]:
                continue
        raise ModelProviderError(
            "Model request failed after retries and configured fallbacks."
        ) from last_error


class ModelRouter:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def complete(
        self, task: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> ModelResponse:
        return await self._provider.generate(task, system, prompt, schema)
