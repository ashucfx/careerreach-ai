from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=500)
    captured_at: datetime
    content: str = Field(min_length=1, max_length=20_000)


class AgentInput(StrictModel):
    goal: str = Field(min_length=10, max_length=10_000)
    context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=lambda: list[Evidence](), max_length=100)


class Finding(StrictModel):
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    confidence: float = Field(ge=0, le=1)


class AgentOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=4_000)
    findings: list[Finding] = Field(default_factory=lambda: list[Finding](), max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=30)
    next_steps: list[str] = Field(default_factory=list, max_length=30)


class WorkflowPlanRequest(AgentInput):
    max_steps: int = Field(default=8, ge=1, le=12)


class PlanStep(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    agent_id: str
    depends_on: list[str] = Field(default_factory=list, max_length=12)


class WorkflowPlan(StrictModel):
    objective: str = Field(min_length=1, max_length=2_000)
    steps: list[PlanStep] = Field(min_length=1, max_length=12)
    approval_required: bool

    @model_validator(mode="after")
    def validate_dependencies(self) -> WorkflowPlan:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow step IDs must be unique")
        known = set(ids)
        for step in self.steps:
            if step.id in step.depends_on:
                raise ValueError("a workflow step cannot depend on itself")
            if set(step.depends_on) - known:
                raise ValueError("workflow dependencies must refer to existing steps")
        resolved: set[str] = set()
        remaining = {step.id: set(step.depends_on) for step in self.steps}
        while remaining:
            ready = {
                step_id for step_id, dependencies in remaining.items() if dependencies <= resolved
            }
            if not ready:
                raise ValueError("workflow dependencies must form an acyclic graph")
            resolved.update(ready)
            for step_id in ready:
                del remaining[step_id]
        return self


class StepResult(StrictModel):
    step_id: str
    agent_id: str
    output: AgentOutput
    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class WorkflowExecution(StrictModel):
    status: Literal["completed"] = "completed"
    objective: str
    approval_required: bool
    results: list[StepResult]


class WorkflowRunStarted(StrictModel):
    run_id: str
    status: Literal["running"] = "running"


class WorkflowRunStatus(StrictModel):
    run_id: str
    status: Literal["running", "completed", "failed", "cancelled", "terminated", "timed_out"]
    result: WorkflowExecution | None = None


class RegistrationRequest(StrictModel):
    email: EmailStr
    password: SecretStr = Field(min_length=15, max_length=128)


class LoginRequest(StrictModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class UserIdentity(StrictModel):
    id: UUID
    email: EmailStr
    created_at: datetime


class CandidateSkillInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    proficiency: Literal["beginner", "intermediate", "advanced", "expert"] | None = None
    years_experience: float | None = Field(default=None, ge=0, le=80)


class CandidateExperienceInput(StrictModel):
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    start_date: datetime
    end_date: datetime | None = None
    currently_employed: bool = False

    @model_validator(mode="after")
    def validate_dates(self) -> CandidateExperienceInput:
        if self.start_date.utcoffset() is None:
            raise ValueError("experience start_date must include a timezone")
        if self.end_date is not None and self.end_date.utcoffset() is None:
            raise ValueError("experience end_date must include a timezone")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("experience end_date must not precede start_date")
        if self.currently_employed and self.end_date is not None:
            raise ValueError("current experience must not have an end_date")
        return self


class CandidateEducationInput(StrictModel):
    institution: str = Field(min_length=1, max_length=200)
    credential: str = Field(min_length=1, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def validate_years(self) -> CandidateEducationInput:
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.end_year < self.start_year
        ):
            raise ValueError("education end_year must not precede start_year")
        return self


class CandidateProfileWrite(StrictModel):
    expected_version: int | None = Field(default=None, ge=1)
    full_name: str = Field(min_length=1, max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=10_000)
    target_titles: list[str] = Field(default_factory=lambda: list[str](), max_length=30)
    target_locations: list[str] = Field(default_factory=lambda: list[str](), max_length=30)
    skills: list[CandidateSkillInput] = Field(
        default_factory=lambda: list[CandidateSkillInput](), max_length=100
    )
    experiences: list[CandidateExperienceInput] = Field(
        default_factory=lambda: list[CandidateExperienceInput](), max_length=100
    )
    education: list[CandidateEducationInput] = Field(
        default_factory=lambda: list[CandidateEducationInput](), max_length=50
    )

    @model_validator(mode="after")
    def validate_unique_names(self) -> CandidateProfileWrite:
        skill_names = [skill.name.casefold() for skill in self.skills]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError("candidate skills must be unique by name")
        return self


class CandidateSkill(StrictModel):
    id: UUID
    name: str
    proficiency: Literal["beginner", "intermediate", "advanced", "expert"] | None
    years_experience: float | None


class CandidateExperience(StrictModel):
    id: UUID
    employer: str
    title: str
    location: str | None
    description: str | None
    start_date: datetime
    end_date: datetime | None
    currently_employed: bool


class CandidateEducation(StrictModel):
    id: UUID
    institution: str
    credential: str
    field_of_study: str | None
    start_year: int | None
    end_year: int | None


class CandidateProfile(StrictModel):
    id: UUID
    user_id: UUID
    version: int
    full_name: str
    headline: str | None
    summary: str | None
    target_titles: list[str]
    target_locations: list[str]
    skills: list[CandidateSkill]
    experiences: list[CandidateExperience]
    education: list[CandidateEducation]
    created_at: datetime
    updated_at: datetime


class CandidateProfileHistory(StrictModel):
    version: int = Field(ge=1)
    snapshot: CandidateProfile
    created_at: datetime


class ResumeFact(StrictModel):
    value: str = Field(min_length=1, max_length=2_000)
    source_quote: str = Field(min_length=1, max_length=1_000)


class ResumeSkillFact(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    proficiency: Literal["beginner", "intermediate", "advanced", "expert"] | None = None
    years_experience: float | None = Field(default=None, ge=0, le=80)
    source_quote: str = Field(min_length=1, max_length=1_000)


class ResumeExperienceFact(StrictModel):
    employer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    start_date_text: str | None = Field(default=None, max_length=100)
    end_date_text: str | None = Field(default=None, max_length=100)
    source_quote: str = Field(min_length=1, max_length=1_000)


class ResumeEducationFact(StrictModel):
    institution: str = Field(min_length=1, max_length=200)
    credential: str = Field(min_length=1, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    source_quote: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_years(self) -> ResumeEducationFact:
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.end_year < self.start_year
        ):
            raise ValueError("education end_year must not precede start_year")
        return self


class ResumeExtraction(StrictModel):
    full_name: ResumeFact | None = None
    headline: ResumeFact | None = None
    summary: ResumeFact | None = None
    target_titles: list[ResumeFact] = Field(
        default_factory=lambda: list[ResumeFact](), max_length=30
    )
    skills: list[ResumeSkillFact] = Field(
        default_factory=lambda: list[ResumeSkillFact](), max_length=100
    )
    experiences: list[ResumeExperienceFact] = Field(
        default_factory=lambda: list[ResumeExperienceFact](), max_length=100
    )
    education: list[ResumeEducationFact] = Field(
        default_factory=lambda: list[ResumeEducationFact](), max_length=50
    )


class ResumeDocumentSummary(StrictModel):
    id: UUID
    file_name: str
    content_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str
    uploaded_at: datetime
    extraction_version: int | None = Field(default=None, ge=1)
    extraction_model: str | None = None


class ResumeDocument(ResumeDocumentSummary):
    extracted_text: str
    extraction: ResumeExtraction | None = None
    extraction_latency_ms: int | None = Field(default=None, ge=0)
    extraction_input_tokens: int | None = Field(default=None, ge=0)
    extraction_output_tokens: int | None = Field(default=None, ge=0)


class JobRequirement(StrictModel):
    requirement: str = Field(min_length=1, max_length=1_000)
    category: Literal[
        "skill",
        "experience",
        "education",
        "responsibility",
        "location",
        "work_authorization",
        "compensation",
        "other",
    ]
    required: bool
    source_quote: str = Field(min_length=1, max_length=1_000)


class JobAnalysis(StrictModel):
    role_summary: str = Field(min_length=1, max_length=4_000)
    summary_quotes: list[str] = Field(min_length=1, max_length=10)
    seniority: str | None = Field(default=None, max_length=120)
    employment_type: str | None = Field(default=None, max_length=120)
    requirements: list[JobRequirement] = Field(
        default_factory=lambda: list[JobRequirement](), max_length=100
    )


class JobSubmission(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    source_url: AnyHttpUrl | None = Field(default=None, max_length=2_000)
    description: str = Field(min_length=100, max_length=50_000)


class JobListingSummary(StrictModel):
    id: UUID
    title: str
    company_name: str
    location: str | None
    source_url: str | None
    source_captured_at: datetime
    version: int = Field(ge=1)
    created_at: datetime


class JobListing(JobListingSummary):
    description: str
    analysis: JobAnalysis
    analysis_model: str
    analysis_latency_ms: int = Field(ge=0)
    analysis_input_tokens: int | None = Field(default=None, ge=0)
    analysis_output_tokens: int | None = Field(default=None, ge=0)


class WebResearchResult(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2_000)
    snippet: str = Field(min_length=1, max_length=4_000)
    captured_at: datetime


class WebResearchResponse(StrictModel):
    provider: Literal["brave_search"] = "brave_search"
    query: str = Field(min_length=1, max_length=500)
    results: list[WebResearchResult] = Field(max_length=20)
    captured_at: datetime


class ResearchIntegrationStatus(StrictModel):
    provider: Literal["brave_search"] = "brave_search"
    configured: bool
    connected: bool | None = None
    checked_at: datetime | None = None
    result_count: int | None = Field(default=None, ge=0)
    message: str


class CompanyResearchRequest(StrictModel):
    company_name: str = Field(min_length=1, max_length=200)
    query: str | None = Field(default=None, min_length=3, max_length=500)
    result_count: int = Field(default=8, ge=1, le=10)


class CompanyEvidenceQuote(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=1_000)


class CompanyResearchFinding(StrictModel):
    category: Literal["overview", "product", "market", "hiring", "culture", "news", "other"]
    claim: str = Field(min_length=1, max_length=2_000)
    source_quotes: list[CompanyEvidenceQuote] = Field(min_length=1, max_length=10)


class CompanyResearchAnalysis(StrictModel):
    summary: str = Field(min_length=1, max_length=4_000)
    summary_quotes: list[CompanyEvidenceQuote] = Field(min_length=1, max_length=10)
    findings: list[CompanyResearchFinding] = Field(min_length=1, max_length=40)


class CompanyResearch(StrictModel):
    id: UUID
    company_id: UUID
    company_name: str
    version: int = Field(ge=1)
    query: str
    analysis: CompanyResearchAnalysis
    sources: list[WebResearchResult]
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime


class CompanyResearchSummary(StrictModel):
    company_id: UUID
    company_name: str
    latest_version: int = Field(ge=1)
    updated_at: datetime


class RecruiterDiscoveryRequest(StrictModel):
    company_name: str = Field(min_length=1, max_length=200)
    target_role: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    result_count: int = Field(default=8, ge=1, le=10)


class RecruiterCandidateFinding(StrictModel):
    full_name: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=2, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    profile_url: AnyHttpUrl | None = None
    evidence_id: str = Field(min_length=1, max_length=128)
    source_quote: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0, le=1)


class RecruiterDiscoveryAnalysis(StrictModel):
    candidates: list[RecruiterCandidateFinding] = Field(max_length=30)


class ContactSource(StrictModel):
    id: UUID
    provider: str
    source_id: str
    source_url: str
    source_title: str
    source_snippet: str
    source_quote: str
    search_query: str
    captured_at: datetime


class RecruiterContact(StrictModel):
    id: UUID
    full_name: str
    title: str
    company_name: str
    location: str | None
    profile_url: str | None
    sources: list[ContactSource]
    created_at: datetime
    updated_at: datetime


class RecruiterDiscoveryResponse(StrictModel):
    query: str
    captured_at: datetime
    recruiters: list[RecruiterContact]


class MatchEvidenceQuote(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=1_000)


class MatchStatement(StrictModel):
    statement: str = Field(min_length=1, max_length=1_000)
    evidence: list[MatchEvidenceQuote] = Field(min_length=1, max_length=10)


class CandidateJobMatchAnalysis(StrictModel):
    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=2_000)
    strengths: list[MatchStatement] = Field(max_length=30)
    gaps: list[MatchStatement] = Field(max_length=30)


class CandidateJobMatch(StrictModel):
    id: UUID
    job_id: UUID
    profile_version: int = Field(ge=1)
    version: int = Field(ge=1)
    analysis: CandidateJobMatchAnalysis
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime


class RecruiterMatchRequest(StrictModel):
    job_id: UUID
    recruiter_ids: list[UUID] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_unique_recruiters(self) -> RecruiterMatchRequest:
        if len(self.recruiter_ids) != len(set(self.recruiter_ids)):
            raise ValueError("recruiter_ids must be unique")
        return self


class RecruiterMatchFinding(StrictModel):
    recruiter_id: UUID
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence: list[MatchEvidenceQuote] = Field(min_length=1, max_length=10)


class RecruiterMatchAnalysis(StrictModel):
    findings: list[RecruiterMatchFinding] = Field(max_length=30)


class RecruiterMatchResult(StrictModel):
    recruiter_id: UUID
    job_id: UUID
    profile_version: int = Field(ge=1)
    version: int = Field(ge=1)
    score: int = Field(ge=0, le=100)
    rationale: str
    evidence: list[MatchEvidenceQuote]
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime


class OutreachDraftRequest(StrictModel):
    recruiter_id: UUID
    job_id: UUID
    tone: Literal["warm", "direct", "formal"] = "warm"
    context: str | None = Field(default=None, max_length=2_000)


class OutreachPoint(StrictModel):
    point: str = Field(min_length=1, max_length=500)
    evidence: list[MatchEvidenceQuote] = Field(min_length=1, max_length=5)


class OutreachStrategy(StrictModel):
    objective: str = Field(min_length=1, max_length=500)
    approach: str = Field(min_length=1, max_length=1_000)
    talking_points: list[OutreachPoint] = Field(min_length=1, max_length=8)
    call_to_action: str = Field(min_length=1, max_length=300)


class OutreachEmail(StrictModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5_000)
    factual_claims: list[OutreachPoint] = Field(max_length=15)


class OutreachDraft(StrictModel):
    id: UUID
    recruiter_id: UUID
    job_id: UUID
    version: int = Field(ge=1)
    strategy: OutreachStrategy
    email: OutreachEmail
    tone: Literal["warm", "direct", "formal"]
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime


class CampaignRecipientInput(StrictModel):
    draft_id: UUID
    recipient_email: EmailStr


class CampaignCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    recipients: list[CampaignRecipientInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_drafts(self) -> CampaignCreateRequest:
        draft_ids = [recipient.draft_id for recipient in self.recipients]
        if len(draft_ids) != len(set(draft_ids)):
            raise ValueError("campaign draft IDs must be unique")
        return self


class CampaignTransitionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class CampaignActionRequest(CampaignTransitionRequest):
    action: Literal["submit", "approve", "reject", "pause", "resume", "cancel", "retry_failed"]


class CampaignRecipient(StrictModel):
    id: UUID
    draft_id: UUID
    draft_version: int = Field(ge=1)
    recipient_email: EmailStr
    status: Literal[
        "pending_approval",
        "approved",
        "queued",
        "sending",
        "sent",
        "failed",
        "unknown",
        "cancelled",
    ]
    email_snapshot: OutreachEmail
    created_at: datetime


class Campaign(StrictModel):
    id: UUID
    name: str
    status: Literal[
        "draft",
        "awaiting_approval",
        "approved",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
    ]
    version: int = Field(ge=1)
    recipients: list[CampaignRecipient]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class CampaignSummary(StrictModel):
    id: UUID
    name: str
    status: Literal[
        "draft",
        "awaiting_approval",
        "approved",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
    ]
    version: int = Field(ge=1)
    recipient_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None


class EmailIntegrationStatus(StrictModel):
    provider: Literal["gmail"] = "gmail"
    configured: bool
    connected: bool
    email: EmailStr | None = None
    scopes: list[str] = Field(default_factory=list)
    message: str


class EmailAuthorizationUrl(StrictModel):
    authorization_url: AnyHttpUrl


class EmailSyncResult(StrictModel):
    provider: Literal["gmail"] = "gmail"
    synced_count: int = Field(ge=0)
    synced_at: datetime


class SyncedEmailMessage(StrictModel):
    provider_message_id: str
    provider_thread_id: str
    sender: str | None
    recipients: list[str]
    subject: str | None
    received_at: datetime | None
    snippet: str
    body_text: str
    labels: list[str]


class AccessToken(StrictModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)


class AgentDescriptor(StrictModel):
    id: str
    name: str
    purpose: str
    tools: list[str]
    permissions: list[str]
    context_requirements: list[str]
    model_task: Literal["reasoning", "communication", "extraction"]
    prompt_version: str
    evaluation_metrics: list[str]
