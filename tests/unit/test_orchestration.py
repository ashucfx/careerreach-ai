import pytest
from careerreach.agents import AGENTS
from careerreach.models import ModelResponse, ModelRouter
from careerreach.orchestration import WorkflowOrchestrator, WorkflowValidationError
from careerreach.schemas import (
    AgentOutput,
    Finding,
    WorkflowPlan,
    WorkflowPlanRequest,
)
from pydantic import BaseModel


class FakeProvider:
    def __init__(self, responses: list[BaseModel]) -> None:
        self.responses = iter(responses)

    async def generate(
        self, task: str, system: str, prompt: str, schema: type[BaseModel]
    ) -> ModelResponse:
        return ModelResponse(next(self.responses), "test-model", 1, 10, 5)


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="acyclic"):
        WorkflowPlan.model_validate(
            {
                "objective": "Research roles",
                "approval_required": False,
                "steps": [
                    {"id": "first", "agent_id": "job-intelligence", "depends_on": ["second"]},
                    {"id": "second", "agent_id": "company-research", "depends_on": ["first"]},
                ],
            }
        )


@pytest.mark.asyncio
async def test_orchestrator_runs_independent_steps_and_preserves_plan_order() -> None:
    plan = WorkflowPlan.model_validate(
        {
            "objective": "Analyze a role and company",
            "approval_required": False,
            "steps": [
                {"id": "job", "agent_id": "job-intelligence", "depends_on": []},
                {"id": "company", "agent_id": "company-research", "depends_on": []},
            ],
        }
    )
    output = AgentOutput(summary="Reviewed supplied context", findings=[], risks=[], next_steps=[])
    provider = FakeProvider([plan, output, output])
    orchestrator = WorkflowOrchestrator(ModelRouter(provider))
    result = await orchestrator.execute(WorkflowPlanRequest(goal="Analyze the role and company"))
    assert [step.step_id for step in result.results] == ["job", "company"]
    assert len(AGENTS) == 12


@pytest.mark.asyncio
async def test_agent_output_cannot_cite_unsupplied_evidence() -> None:
    plan = WorkflowPlan.model_validate(
        {
            "objective": "Analyze a role",
            "approval_required": False,
            "steps": [{"id": "job", "agent_id": "job-intelligence", "depends_on": []}],
        }
    )
    output = AgentOutput(
        summary="Reviewed supplied context",
        findings=[Finding(statement="A requirement", evidence_ids=["missing"], confidence=0.8)],
    )
    orchestrator = WorkflowOrchestrator(ModelRouter(FakeProvider([plan, output])))
    with pytest.raises(WorkflowValidationError, match="evidence"):
        await orchestrator.execute(WorkflowPlanRequest(goal="Analyze the role", evidence=[]))
