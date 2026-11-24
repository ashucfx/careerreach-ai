from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from .config import get_settings
from .models import ModelRouter, OpenAICompatibleProvider
from .orchestration import WorkflowOrchestrator
from .temporal_workflows import CareerReachWorkflow


class AgentActivities:
    def __init__(
        self, orchestrator: WorkflowOrchestrator, checkpointer: AsyncPostgresSaver
    ) -> None:
        self._orchestrator = orchestrator
        self._checkpointer = checkpointer

    @activity.defn(name="execute_agent_graph")
    async def execute_agent_graph(self, input_data: dict[str, Any]) -> dict[str, Any]:
        from .graph import build_agent_graph

        request = input_data["request"]
        thread_id = input_data["thread_id"]
        graph = build_agent_graph(self._orchestrator, self._checkpointer)
        from .graph import AgentGraphState

        initial_state: AgentGraphState = {
            "request": request,
            "plan": {},
            "pending_steps": [],
            "results": {},
            "execution": {},
        }
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        previous_checkpoint = await self._checkpointer.aget_tuple(config)
        state = await graph.ainvoke(
            None if previous_checkpoint is not None else initial_state,
            config=config,
        )
        return state["execution"]


async def run_worker() -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Set CAREERREACH_DATABASE_URL before starting the worker.")
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        connect_timeout=timedelta(seconds=10),
    )
    async with httpx.AsyncClient() as http_client:
        provider = OpenAICompatibleProvider(settings, http_client)
        orchestrator = WorkflowOrchestrator(ModelRouter(provider))
        async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
            await checkpointer.setup()
            activities = AgentActivities(orchestrator, checkpointer)
            worker = Worker(
                client,
                task_queue=settings.temporal_task_queue,
                workflows=[CareerReachWorkflow],
                activities=[activities.execute_agent_graph],
                max_concurrent_activities=8,
            )
            await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
