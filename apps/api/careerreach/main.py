from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal, cast
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg import Error as PostgresError
from temporalio.client import Client
from temporalio.service import RPCError

from .agents import list_agents
from .auth import (
    AuthConfigurationError,
    AuthenticatedPrincipal,
    AuthService,
    DuplicateUserError,
    InvalidCredentialsError,
    get_current_principal,
)
from .config import get_settings
from .models import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRouter,
    OpenAICompatibleProvider,
)
from .orchestration import WorkflowOrchestrator, WorkflowValidationError
from .schemas import (
    AccessToken,
    AgentDescriptor,
    LoginRequest,
    RegistrationRequest,
    UserIdentity,
    WorkflowExecution,
    WorkflowPlan,
    WorkflowPlanRequest,
    WorkflowRunStarted,
    WorkflowRunStatus,
)
from .temporal_workflows import CareerReachWorkflow

_AUTHENTICATED_PRINCIPAL = Depends(get_current_principal)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    client = httpx.AsyncClient()
    provider = OpenAICompatibleProvider(settings, client)
    temporal_client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        lazy=True,
    )
    app.state.provider = provider
    app.state.orchestrator = WorkflowOrchestrator(ModelRouter(provider))
    app.state.auth_service = AuthService(settings)
    app.state.temporal_client = temporal_client
    yield
    await client.aclose()


app = FastAPI(title="CareerReach AI API", version="0.1.0", lifespan=lifespan)


@app.post("/api/v1/auth/register", response_model=UserIdentity, status_code=201)
async def register(request: RegistrationRequest, web_request: Request) -> UserIdentity:
    service: AuthService = web_request.app.state.auth_service
    try:
        return await service.register(request)
    except DuplicateUserError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The account database is unavailable.") from exc


@app.post("/api/v1/auth/token", response_model=AccessToken)
async def login(request: LoginRequest, web_request: Request) -> AccessToken:
    service: AuthService = web_request.app.state.auth_service
    try:
        return await service.login(request)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The account database is unavailable.") from exc


@app.get("/api/v1/auth/me", response_model=UserIdentity)
async def current_user(
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> UserIdentity:
    return principal.user


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> None:
    service: AuthService = web_request.app.state.auth_service
    try:
        await service.revoke(principal)
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The account database is unavailable.") from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/agents", response_model=list[AgentDescriptor])
async def agents() -> list[AgentDescriptor]:
    return list_agents()


@app.post("/api/v1/workflows/plan", response_model=WorkflowPlan)
async def plan_workflow(
    request: WorkflowPlanRequest,
    web_request: Request,
    _principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> WorkflowPlan:
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
async def execute_workflow(
    request: WorkflowPlanRequest,
    web_request: Request,
    _principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> WorkflowExecution:
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


@app.post("/api/v1/workflow-runs", response_model=WorkflowRunStarted, status_code=202)
async def start_workflow(
    request: WorkflowPlanRequest,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> WorkflowRunStarted:
    settings = get_settings()
    if settings.model_api_key is None:
        raise HTTPException(
            status_code=503, detail="Set CAREERREACH_MODEL_API_KEY to start workflows."
        )
    client: Client = web_request.app.state.temporal_client
    run_id = f"careerreach-{principal.user.id.hex}-{uuid4().hex}"
    try:
        handle = await client.start_workflow(
            CareerReachWorkflow.run,
            request.model_dump(mode="json"),
            id=run_id,
            task_queue=settings.temporal_task_queue,
        )
    except RPCError as exc:
        raise HTTPException(
            status_code=503, detail="Temporal is unavailable for workflow execution."
        ) from exc
    return WorkflowRunStarted(run_id=handle.id)


@app.get("/api/v1/workflow-runs/{run_id}", response_model=WorkflowRunStatus)
async def get_workflow_run(
    run_id: str,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> WorkflowRunStatus:
    if not run_id.startswith(f"careerreach-{principal.user.id.hex}-"):
        raise HTTPException(status_code=404, detail="Workflow run was not found.")
    client: Client = web_request.app.state.temporal_client
    handle = client.get_workflow_handle(run_id)
    try:
        description = await handle.describe()
        if description.status is None:
            raise HTTPException(status_code=502, detail="Temporal returned no workflow status.")
        status_name = description.status.name
        status = status_name.removeprefix("WORKFLOW_EXECUTION_STATUS_")
        result = await handle.result() if status == "COMPLETED" else None
    except RPCError as exc:
        raise HTTPException(
            status_code=503, detail="Temporal is unavailable for workflow status."
        ) from exc
    status_map = {
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "CANCELED": "cancelled",
        "TERMINATED": "terminated",
        "TIMED_OUT": "timed_out",
    }
    normalized = status_map.get(status)
    if normalized is None:
        raise HTTPException(
            status_code=502, detail="Temporal returned an unsupported workflow status."
        )
    return WorkflowRunStatus(
        run_id=run_id,
        status=cast(
            Literal["running", "completed", "failed", "cancelled", "terminated", "timed_out"],
            normalized,
        ),
        result=WorkflowExecution.model_validate(result) if result is not None else None,
    )
