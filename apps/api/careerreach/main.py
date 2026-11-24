from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from .agents import list_agents
from .config import get_settings
from .models import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRouter,
    OpenAICompatibleProvider,
)
from .orchestration import WorkflowOrchestrator, WorkflowValidationError
from .schemas import AgentDescriptor, WorkflowExecution, WorkflowPlan, WorkflowPlanRequest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    client = httpx.AsyncClient()
    provider = OpenAICompatibleProvider(settings, client)
    app.state.provider = provider
    app.state.orchestrator = WorkflowOrchestrator(ModelRouter(provider))
    yield
    await client.aclose()


app = FastAPI(title="CareerReach AI API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/agents", response_model=list[AgentDescriptor])
async def agents() -> list[AgentDescriptor]:
    return list_agents()


@app.post("/api/v1/workflows/plan", response_model=WorkflowPlan)
async def plan_workflow(request: WorkflowPlanRequest, web_request: Request) -> WorkflowPlan:
    orchestrator: WorkflowOrchestrator = web_request.app.state.orchestrator
    try:
        return await orchestrator.plan(request)
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail="The model provider request failed.") from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504, detail="The agent exceeded its execution timeout."
        ) from exc


@app.post("/api/v1/workflows/execute", response_model=WorkflowExecution)
async def execute_workflow(request: WorkflowPlanRequest, web_request: Request) -> WorkflowExecution:
    orchestrator: WorkflowOrchestrator = web_request.app.state.orchestrator
    try:
        return await orchestrator.execute(request)
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail="The model provider request failed.") from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504, detail="The agent exceeded its execution timeout."
        ) from exc
