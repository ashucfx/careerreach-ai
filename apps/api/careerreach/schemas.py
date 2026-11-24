from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class Finding(StrictModel):
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    confidence: float = Field(ge=0, le=1)


class AgentOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=4_000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
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
