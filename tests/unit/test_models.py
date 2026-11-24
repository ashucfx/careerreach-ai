import json

import httpx
import pytest
from careerreach.config import Settings
from careerreach.models import ModelConfigurationError, OpenAICompatibleProvider
from careerreach.schemas import AgentOutput
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_openai_compatible_provider_validates_structured_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        output = json.dumps({"summary": "Complete", "findings": [], "risks": [], "next_steps": []})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": output}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(Settings(model_api_key=SecretStr("test-key")), client)
    result = await provider.generate("extraction", "system", "prompt", AgentOutput)
    assert result.value.summary == "Complete"
    assert result.input_tokens == 4
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_requires_credentials_instead_of_returning_fake_data() -> None:
    provider = OpenAICompatibleProvider(Settings(), httpx.AsyncClient())
    with pytest.raises(ModelConfigurationError, match="CAREERREACH_MODEL_API_KEY"):
        await provider.generate("reasoning", "system", "prompt", AgentOutput)


def test_unknown_model_task_fails_explicitly() -> None:
    provider = OpenAICompatibleProvider(Settings(model_api_key=SecretStr("key")))
    with pytest.raises(ModelConfigurationError, match="No model route"):
        provider.model_for("unknown")
