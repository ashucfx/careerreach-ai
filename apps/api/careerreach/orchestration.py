from __future__ import annotations

import asyncio
import json
from typing import Any

from .agents import AGENTS
from .models import ModelRouter
from .schemas import (
    AgentInput,
    AgentOutput,
    PlanStep,
    StepResult,
    WorkflowExecution,
    WorkflowPlan,
    WorkflowPlanRequest,
)


class WorkflowValidationError(ValueError):
    pass


_PLAN_INSTRUCTIONS = (
    "Create a concise execution plan using only the listed agent IDs. "
    "Use dependencies when one step needs another step's output. "
    "Set approval_required true if the goal asks to send, schedule, or otherwise act externally. "
    "This system prepares work only; external actions are never executed by these agents. "
    "Return JSON with objective, steps, and approval_required."
)


class WorkflowOrchestrator:
    def __init__(self, router: ModelRouter, max_concurrency: int = 4) -> None:
        self._router = router
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def plan(self, request: WorkflowPlanRequest) -> WorkflowPlan:
        available = sorted(AGENTS)
        prompt = json.dumps(
            {
                "goal": request.goal,
                "context": request.context,
                "max_steps": request.max_steps,
                "available_agents": available,
            },
            default=str,
        )
        response = await self._router.complete(
            "reasoning", _PLAN_INSTRUCTIONS, prompt, WorkflowPlan
        )
        plan = WorkflowPlan.model_validate(response.value.model_dump())
        if len(plan.steps) > request.max_steps:
            raise WorkflowValidationError("planned workflow exceeds the requested step limit")
        unknown = {step.agent_id for step in plan.steps} - AGENTS.keys()
        if unknown:
            raise WorkflowValidationError(
                f"plan references unavailable agents: {', '.join(sorted(unknown))}"
            )
        return plan

    async def execute(self, request: WorkflowPlanRequest) -> WorkflowExecution:
        plan = await self.plan(request)
        results: dict[str, StepResult] = {}
        pending = {step.id: step for step in plan.steps}
        evidence_ids = {item.id for item in request.evidence}

        while pending:
            ready = [step for step in pending.values() if set(step.depends_on) <= results.keys()]
            if not ready:
                raise WorkflowValidationError("workflow could not make progress")
            batch = await asyncio.gather(
                *(self._execute_step(step, request, results, evidence_ids) for step in ready)
            )
            for result in batch:
                results[result.step_id] = result
                del pending[result.step_id]

        return WorkflowExecution(
            objective=plan.objective,
            approval_required=plan.approval_required,
            results=[results[step.id] for step in plan.steps],
        )

    async def _execute_step(
        self,
        step: PlanStep,
        request: AgentInput,
        results: dict[str, StepResult],
        evidence_ids: set[str],
    ) -> StepResult:
        definition = AGENTS[step.agent_id]
        previous = {
            dependency: results[dependency].output.model_dump() for dependency in step.depends_on
        }
        agent_input: dict[str, Any] = {
            "goal": request.goal,
            "context": {**request.context, "prior_step_results": previous},
            "evidence": [item.model_dump(mode="json") for item in request.evidence],
        }
        prompt = json.dumps(agent_input, default=str)
        async with self._semaphore:
            response = await asyncio.wait_for(
                self._router.complete(
                    definition.descriptor.model_task,
                    definition.instructions,
                    prompt,
                    definition.output_schema,
                ),
                timeout=definition.timeout_seconds,
            )
        output = AgentOutput.model_validate(response.value.model_dump())
        cited_ids = {
            evidence_id for finding in output.findings for evidence_id in finding.evidence_ids
        }
        if cited_ids - evidence_ids:
            raise WorkflowValidationError(
                f"agent '{step.agent_id}' cited evidence that was not supplied"
            )
        return StepResult(
            step_id=step.id,
            agent_id=step.agent_id,
            output=output,
            model=response.model,
            prompt_version=definition.descriptor.prompt_version,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
