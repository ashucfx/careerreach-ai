from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="careerreach.execute-agent-workflow")
class CareerReachWorkflow:
    @workflow.run
    async def run(self, request: dict[str, object]) -> dict[str, object]:
        workflow_id = workflow.info().workflow_id
        return await workflow.execute_activity(
            "execute_agent_graph",
            {"request": request, "thread_id": workflow_id},
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=3,
            ),
        )
