from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .orchestration import WorkflowOrchestrator, WorkflowValidationError
from .schemas import PlanStep, StepResult, WorkflowExecution, WorkflowPlan, WorkflowPlanRequest


class AgentGraphState(TypedDict):
    request: dict[str, Any]
    plan: dict[str, Any]
    pending_steps: list[dict[str, Any]]
    results: dict[str, dict[str, Any]]
    execution: dict[str, Any]


class AgentGraphUpdate(TypedDict, total=False):
    plan: dict[str, Any]
    pending_steps: list[dict[str, Any]]
    results: dict[str, dict[str, Any]]
    execution: dict[str, Any]


def build_agent_graph(
    orchestrator: WorkflowOrchestrator,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    max_concurrency: int = 4,
):
    semaphore = asyncio.Semaphore(max_concurrency)

    async def create_plan(state: AgentGraphState) -> AgentGraphUpdate:
        request = WorkflowPlanRequest.model_validate(state["request"])
        plan = await orchestrator.plan(request)
        return {
            "plan": plan.model_dump(mode="json"),
            "pending_steps": [step.model_dump(mode="json") for step in plan.steps],
            "results": {},
        }

    async def execute_ready_batch(state: AgentGraphState) -> AgentGraphUpdate:
        request = WorkflowPlanRequest.model_validate(state["request"])
        pending = [PlanStep.model_validate(step) for step in state["pending_steps"]]
        results = {
            step_id: StepResult.model_validate(value) for step_id, value in state["results"].items()
        }
        ready = [step for step in pending if set(step.depends_on) <= results.keys()]
        if not ready:
            raise WorkflowValidationError("workflow could not make progress")
        evidence_ids = {item.id for item in request.evidence}

        async def execute(step: PlanStep) -> StepResult:
            async with semaphore:
                return await orchestrator.execute_step(step, request, results, evidence_ids)

        batch = await asyncio.gather(*(execute(step) for step in ready))
        updated_results = {key: value.model_dump(mode="json") for key, value in results.items()}
        for result in batch:
            updated_results[result.step_id] = result.model_dump(mode="json")
        completed_ids = {result.step_id for result in batch}
        updated_pending = [
            step.model_dump(mode="json") for step in pending if step.id not in completed_ids
        ]
        return {"results": updated_results, "pending_steps": updated_pending}

    def route_after_batch(state: AgentGraphState) -> str:
        return "execute_ready_batch" if state["pending_steps"] else "assemble_result"

    async def assemble_result(state: AgentGraphState) -> AgentGraphUpdate:
        plan = WorkflowPlan.model_validate(state["plan"])
        results = {
            step_id: StepResult.model_validate(value) for step_id, value in state["results"].items()
        }
        execution = WorkflowExecution(
            objective=plan.objective,
            approval_required=plan.approval_required,
            results=[results[step.id] for step in plan.steps],
        )
        return {"execution": execution.model_dump(mode="json")}

    graph = StateGraph(AgentGraphState)
    graph.add_node("create_plan", create_plan)
    graph.add_node("execute_ready_batch", execute_ready_batch)
    graph.add_node("assemble_result", assemble_result)
    graph.add_edge(START, "create_plan")
    graph.add_edge("create_plan", "execute_ready_batch")
    graph.add_conditional_edges(
        "execute_ready_batch",
        route_after_batch,
        {"execute_ready_batch": "execute_ready_batch", "assemble_result": "assemble_result"},
    )
    graph.add_edge("assemble_result", END)
    return graph.compile(checkpointer=checkpointer)
