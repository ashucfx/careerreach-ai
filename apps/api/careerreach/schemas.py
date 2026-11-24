from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator


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
