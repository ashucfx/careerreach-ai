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


@workflow.defn(name="careerreach.execute-approved-campaign")
class ApprovedCampaignWorkflow:
    @workflow.run
    async def run(self, input_data: dict[str, str]) -> dict[str, object]:
        recipient_ids = await workflow.execute_activity(
            "begin_approved_campaign",
            input_data,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=20),
                maximum_attempts=5,
            ),
        )
        outcomes: list[str] = []
        for recipient_id in recipient_ids:
            activity_input = {**input_data, "recipient_id": recipient_id}
            try:
                outcome = await workflow.execute_activity(
                    "send_campaign_recipient",
                    activity_input,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )
                outcomes.append(outcome)
            except Exception as exc:
                await workflow.execute_activity(
                    "finish_campaign",
                    input_data,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                raise RuntimeError("Campaign recipient activity failed.") from exc
        status = await workflow.execute_activity(
            "finish_campaign",
            input_data,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return {"campaign_id": input_data["campaign_id"], "status": status, "recipients": outcomes}
