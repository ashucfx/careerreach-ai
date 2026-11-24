from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal, cast
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
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
from .job_intelligence import (
    CompanyEvidenceValidationError,
    CompanyResearchNotFound,
    JobEvidenceValidationError,
    JobIntelligenceService,
    JobNotFound,
    NoResearchSources,
)
from .models import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRouter,
    OpenAICompatibleProvider,
)
from .orchestration import WorkflowOrchestrator, WorkflowValidationError
from .outreach import OutreachContextNotFound, OutreachDraftService, OutreachEvidenceError
from .profiles import CandidateProfileService, ProfileVersionConflict, ProfileVersionRequired
from .recruiter_discovery import (
    DiscoveryEvidenceError,
    ProfileRequired,
    RecruiterDiscoveryService,
)
from .resume_parser import (
    MAX_RESUME_BYTES,
    InvalidResumeDocument,
    ResumeFileTooLarge,
    UnsupportedResumeType,
)
from .resumes import (
    ResumeEvidenceValidationError,
    ResumeNotFound,
    ResumeService,
    ResumeTextTooLongForExtraction,
)
from .schemas import (
    AccessToken,
    AgentDescriptor,
    CandidateJobMatch,
    CandidateProfile,
    CandidateProfileHistory,
    CandidateProfileWrite,
    CompanyResearch,
    CompanyResearchRequest,
    CompanyResearchSummary,
    JobListing,
    JobListingSummary,
    JobSubmission,
    LoginRequest,
    OutreachDraft,
    OutreachDraftRequest,
    RecruiterContact,
    RecruiterDiscoveryRequest,
    RecruiterDiscoveryResponse,
    RecruiterMatchRequest,
    RecruiterMatchResult,
    RegistrationRequest,
    ResearchIntegrationStatus,
    ResumeDocument,
    ResumeDocumentSummary,
    UserIdentity,
    WebResearchResponse,
    WorkflowExecution,
    WorkflowPlan,
    WorkflowPlanRequest,
    WorkflowRunStarted,
    WorkflowRunStatus,
)
from .temporal_workflows import CareerReachWorkflow
from .upload_limits import ResumeUploadLimitMiddleware
from .web_research import BraveSearchProvider, SearchNotConfigured, SearchProviderError

_AUTHENTICATED_PRINCIPAL = Depends(get_current_principal)
_RESUME_FILE_UPLOAD = File(...)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    client = httpx.AsyncClient()
    provider = OpenAICompatibleProvider(settings, client)
    model_router = ModelRouter(provider)
    search_provider = BraveSearchProvider(settings, client)
    temporal_client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        lazy=True,
    )
    app.state.provider = provider
    app.state.orchestrator = WorkflowOrchestrator(model_router)
    app.state.auth_service = AuthService(settings)
    app.state.profile_service = CandidateProfileService(settings)
    app.state.resume_service = ResumeService(settings, model_router)
    app.state.search_provider = search_provider
    app.state.job_intelligence_service = JobIntelligenceService(
        settings, model_router, search_provider
    )
    app.state.recruiter_discovery_service = RecruiterDiscoveryService(
        settings,
        model_router,
        search_provider,
        app.state.profile_service,
        app.state.job_intelligence_service,
    )
    app.state.outreach_draft_service = OutreachDraftService(
        settings,
        model_router,
        app.state.profile_service,
        app.state.job_intelligence_service,
        app.state.recruiter_discovery_service,
    )
    app.state.temporal_client = temporal_client
    yield
    await client.aclose()


app = FastAPI(title="CareerReach AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(ResumeUploadLimitMiddleware)


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


@app.get("/api/v1/profile", response_model=CandidateProfile)
async def get_profile(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> CandidateProfile:
    service: CandidateProfileService = web_request.app.state.profile_service
    try:
        profile = await service.get(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The profile database is unavailable.") from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Candidate profile was not found.")
    return profile


@app.put("/api/v1/profile", response_model=CandidateProfile)
async def save_profile(
    profile_request: CandidateProfileWrite,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> CandidateProfile:
    service: CandidateProfileService = web_request.app.state.profile_service
    try:
        return await service.save(principal.user.id, profile_request)
    except ProfileVersionRequired as exc:
        raise HTTPException(status_code=428, detail=str(exc)) from exc
    except ProfileVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The profile database is unavailable.") from exc


@app.get("/api/v1/profile/history", response_model=list[CandidateProfileHistory])
async def profile_history(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[CandidateProfileHistory]:
    service: CandidateProfileService = web_request.app.state.profile_service
    try:
        return await service.history(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The profile database is unavailable.") from exc


@app.delete("/api/v1/profile", status_code=204)
async def delete_profile(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> None:
    service: CandidateProfileService = web_request.app.state.profile_service
    try:
        await service.delete(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The profile database is unavailable.") from exc


@app.post("/api/v1/resumes", response_model=ResumeDocument, status_code=201)
async def upload_resume(
    web_request: Request,
    file: UploadFile = _RESUME_FILE_UPLOAD,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> ResumeDocument:
    try:
        payload = await file.read(MAX_RESUME_BYTES + 1)
    finally:
        await file.close()
    if len(payload) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume files must be 5 MiB or smaller.")
    service: ResumeService = web_request.app.state.resume_service
    try:
        return await service.ingest(
            principal.user.id,
            file.filename or "",
            file.content_type or "application/octet-stream",
            payload,
        )
    except UnsupportedResumeType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except InvalidResumeDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ResumeFileTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The resume database is unavailable.") from exc


@app.get("/api/v1/resumes", response_model=list[ResumeDocumentSummary])
async def list_resumes(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[ResumeDocumentSummary]:
    service: ResumeService = web_request.app.state.resume_service
    try:
        return await service.list(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The resume database is unavailable.") from exc


@app.get("/api/v1/resumes/{resume_id}", response_model=ResumeDocument)
async def get_resume(
    resume_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> ResumeDocument:
    service: ResumeService = web_request.app.state.resume_service
    try:
        document = await service.get(principal.user.id, resume_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The resume database is unavailable.") from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Resume document was not found.")
    return document


@app.post("/api/v1/resumes/{resume_id}/extract", response_model=ResumeDocument)
async def extract_resume(
    resume_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> ResumeDocument:
    service: ResumeService = web_request.app.state.resume_service
    try:
        return await service.extract(principal.user.id, resume_id)
    except ResumeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResumeEvidenceValidationError as exc:
        raise HTTPException(
            status_code=502, detail="Resume extraction failed evidence validation."
        ) from exc
    except ResumeTextTooLongForExtraction as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=502, detail="The resume extraction model request failed."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The resume database is unavailable.") from exc


@app.delete("/api/v1/resumes/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> None:
    service: ResumeService = web_request.app.state.resume_service
    try:
        await service.delete(principal.user.id, resume_id)
    except ResumeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The resume database is unavailable.") from exc


@app.get("/api/v1/integrations", response_model=list[ResearchIntegrationStatus])
async def integrations(
    web_request: Request,
    _principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[ResearchIntegrationStatus]:
    provider: BraveSearchProvider = web_request.app.state.search_provider
    configured = provider.configured
    return [
        ResearchIntegrationStatus(
            configured=configured,
            connected=False if not configured else None,
            message=(
                "Set CAREERREACH_BRAVE_SEARCH_API_KEY to enable web research."
                if not configured
                else "Configured; run the connection test to verify access."
            ),
        )
    ]


@app.post("/api/v1/outreach/drafts", response_model=OutreachDraft, status_code=201)
async def create_outreach_draft(
    request: OutreachDraftRequest,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> OutreachDraft:
    service: OutreachDraftService = web_request.app.state.outreach_draft_service
    try:
        return await service.create(principal.user.id, request)
    except (OutreachContextNotFound, JobNotFound) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProfileRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachEvidenceError as exc:
        raise HTTPException(
            status_code=502, detail="Outreach draft failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail="The outreach model request failed.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The outreach database is unavailable."
        ) from exc


@app.post("/api/v1/recruiters/discover", response_model=RecruiterDiscoveryResponse, status_code=201)
async def discover_recruiters(
    request: RecruiterDiscoveryRequest,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> RecruiterDiscoveryResponse:
    service: RecruiterDiscoveryService = web_request.app.state.recruiter_discovery_service
    try:
        return await service.discover(principal.user.id, request)
    except SearchNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SearchProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DiscoveryEvidenceError as exc:
        raise HTTPException(
            status_code=502, detail="Recruiter discovery failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=502, detail="The recruiter discovery model request failed."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The recruiter database is unavailable."
        ) from exc


@app.get("/api/v1/recruiters", response_model=list[RecruiterContact])
async def list_recruiters(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[RecruiterContact]:
    service: RecruiterDiscoveryService = web_request.app.state.recruiter_discovery_service
    try:
        return await service.list_contacts(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The recruiter database is unavailable."
        ) from exc


@app.post("/api/v1/jobs/{job_id}/match", response_model=CandidateJobMatch, status_code=201)
async def match_job(
    job_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> CandidateJobMatch:
    service: RecruiterDiscoveryService = web_request.app.state.recruiter_discovery_service
    try:
        return await service.match_job(principal.user.id, job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProfileRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DiscoveryEvidenceError as exc:
        raise HTTPException(
            status_code=502, detail="Candidate matching failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail="The matching model request failed.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The matching database is unavailable."
        ) from exc


@app.post("/api/v1/recruiters/match", response_model=list[RecruiterMatchResult], status_code=201)
async def match_recruiters(
    request: RecruiterMatchRequest,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[RecruiterMatchResult]:
    service: RecruiterDiscoveryService = web_request.app.state.recruiter_discovery_service
    try:
        return await service.match_recruiters(principal.user.id, request)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProfileRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DiscoveryEvidenceError as exc:
        raise HTTPException(
            status_code=502, detail="Recruiter matching failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail="The matching model request failed.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The matching database is unavailable."
        ) from exc


@app.post("/api/v1/integrations/brave-search/test", response_model=ResearchIntegrationStatus)
async def test_search_connection(
    web_request: Request,
    _principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> ResearchIntegrationStatus:
    provider: BraveSearchProvider = web_request.app.state.search_provider
    try:
        result = await provider.test_connection()
    except SearchNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SearchProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ResearchIntegrationStatus(
        configured=True,
        connected=True,
        checked_at=result.captured_at,
        result_count=len(result.results),
        message="Brave Search connection succeeded.",
    )


@app.get("/api/v1/research/search", response_model=WebResearchResponse)
async def web_search(
    web_request: Request,
    query: str = Query(min_length=3, max_length=500),
    count: int = Query(default=8, ge=1, le=10),
    _principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> WebResearchResponse:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.search(query, count)
    except SearchNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SearchProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/jobs", response_model=JobListing, status_code=201)
async def analyze_job(
    submission: JobSubmission,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> JobListing:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.analyze_job(principal.user.id, submission)
    except JobEvidenceValidationError as exc:
        raise HTTPException(
            status_code=502, detail="Job analysis failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=502, detail="The job analysis model request failed."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The job database is unavailable.") from exc


@app.get("/api/v1/jobs", response_model=list[JobListingSummary])
async def list_jobs(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[JobListingSummary]:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.list_jobs(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The job database is unavailable.") from exc


@app.get("/api/v1/jobs/{job_id}", response_model=JobListing)
async def get_job(
    job_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> JobListing:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.get_job(principal.user.id, job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The job database is unavailable.") from exc


@app.delete("/api/v1/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> None:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        await service.delete_job(principal.user.id, job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The job database is unavailable.") from exc


@app.post("/api/v1/companies/research", response_model=CompanyResearch, status_code=201)
async def research_company(
    request: CompanyResearchRequest,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> CompanyResearch:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.research_company(principal.user.id, request)
    except SearchNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SearchProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except NoResearchSources as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CompanyEvidenceValidationError as exc:
        raise HTTPException(
            status_code=502, detail="Company research failed evidence validation."
        ) from exc
    except ModelConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=502, detail="The company research model request failed."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The company research database is unavailable."
        ) from exc


@app.get("/api/v1/companies/research", response_model=list[CompanyResearchSummary])
async def list_company_research(
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> list[CompanyResearchSummary]:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.list_company_research(principal.user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The company research database is unavailable."
        ) from exc


@app.get("/api/v1/companies/{company_id}/research", response_model=CompanyResearch)
async def get_company_research(
    company_id: UUID,
    web_request: Request,
    principal: AuthenticatedPrincipal = _AUTHENTICATED_PRINCIPAL,
) -> CompanyResearch:
    service: JobIntelligenceService = web_request.app.state.job_intelligence_service
    try:
        return await service.get_company_research(principal.user.id, company_id)
    except CompanyResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(
            status_code=503, detail="The company research database is unavailable."
        ) from exc


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
