from dataclasses import dataclass
from typing import Literal

from .schemas import AgentDescriptor, AgentInput, AgentOutput

ModelTask = Literal["reasoning", "communication", "extraction"]


@dataclass(frozen=True)
class AgentDefinition:
    descriptor: AgentDescriptor
    instructions: str
    input_schema: type[AgentInput] = AgentInput
    output_schema: type[AgentOutput] = AgentOutput
    timeout_seconds: float = 45.0
    max_retries: int = 2


def _agent(
    agent_id: str,
    name: str,
    purpose: str,
    task: ModelTask,
    permissions: list[str],
    context: list[str],
    metrics: list[str],
    instructions: str,
) -> AgentDefinition:
    return AgentDefinition(
        descriptor=AgentDescriptor(
            id=agent_id,
            name=name,
            purpose=purpose,
            tools=[],
            permissions=permissions,
            context_requirements=context,
            model_task=task,
            prompt_version="1.0.0",
            evaluation_metrics=metrics,
        ),
        instructions=instructions,
    )


_EVIDENCE_RULE = (
    "Use only supplied context and evidence. Never invent facts or achievements. "
    "Cite evidence IDs for factual findings."
)


def _grounded(instructions: str) -> str:
    return f"{instructions} {_EVIDENCE_RULE}"


AGENTS: dict[str, AgentDefinition] = {
    "career-profile-intelligence": _agent(
        "career-profile-intelligence",
        "Career Profile Intelligence Agent",
        "Extract and organize candidate career information.",
        "extraction",
        ["read_supplied_candidate_context"],
        ["candidate_profile", "resume_evidence"],
        ["extraction_accuracy", "unsupported_claim_rate"],
        f"Organize supplied candidate facts into useful career findings. {_EVIDENCE_RULE}",
    ),
    "job-intelligence": _agent(
        "job-intelligence",
        "Job Intelligence Agent",
        "Parse job requirements and role signals.",
        "extraction",
        ["read_supplied_job_context"],
        ["job_description", "job_metadata"],
        ["requirement_extraction_accuracy", "unsupported_claim_rate"],
        _grounded("Identify explicit requirements and distinguish them from inferred preferences."),
    ),
    "company-research": _agent(
        "company-research",
        "Company Research Agent",
        "Analyze supplied company research.",
        "reasoning",
        ["read_supplied_company_context"],
        ["company_evidence"],
        ["source_quality", "factuality"],
        f"Summarize only the company evidence supplied in context. {_EVIDENCE_RULE}",
    ),
    "recruiter-discovery": _agent(
        "recruiter-discovery",
        "Recruiter Discovery Agent",
        "Identify recruiter candidates from supplied records.",
        "reasoning",
        ["read_supplied_contact_records"],
        ["contact_records", "target_roles"],
        ["discovery_relevance", "source_quality"],
        _grounded(
            "Assess supplied records for recruiter relevance. Do not invent or infer identities."
        ),
    ),
    "contact-verification": _agent(
        "contact-verification",
        "Contact Enrichment and Verification Agent",
        "Review contact fields and verification evidence.",
        "extraction",
        ["read_supplied_contact_records"],
        ["contact_records", "verification_sources"],
        ["verification_precision", "unsupported_claim_rate"],
        _grounded(
            "Report only verification supported by supplied sources; unknown fields remain unknown."
        ),
    ),
    "candidate-job-recruiter-matching": _agent(
        "candidate-job-recruiter-matching",
        "Candidate-Job-Recruiter Matching Agent",
        "Explain relevance between supplied candidate, job, and recruiter evidence.",
        "reasoning",
        ["read_supplied_matching_context"],
        ["candidate_profile", "job_analysis", "contact_records"],
        ["matching_accuracy", "explanation_grounding"],
        _grounded("Compare supplied profile, role, and contact evidence. Explain uncertainty."),
    ),
    "outreach-strategy": _agent(
        "outreach-strategy",
        "Outreach Strategy Agent",
        "Recommend an evidence-based outreach approach.",
        "reasoning",
        ["read_supplied_outreach_context"],
        ["candidate_profile", "contact_context", "preferences"],
        ["strategy_relevance", "policy_compliance"],
        f"Suggest respectful outreach strategy. Do not initiate contact. {_EVIDENCE_RULE}",
    ),
    "email-personalization": _agent(
        "email-personalization",
        "Email Personalization Agent",
        "Draft a personalized email from supplied facts.",
        "communication",
        ["read_supplied_outreach_context"],
        ["candidate_profile", "recipient_context", "preferences"],
        ["personalization_quality", "factuality", "policy_compliance"],
        _grounded("Draft a concise, truthful message using supplied facts only. Never send it."),
    ),
    "campaign-execution": _agent(
        "campaign-execution",
        "Campaign Execution Agent",
        "Prepare campaign execution steps for approval.",
        "reasoning",
        ["read_approved_campaign_context"],
        ["approved_campaign", "recipients"],
        ["workflow_completion", "policy_compliance"],
        "Prepare a campaign checklist. Never send messages or modify external systems.",
    ),
    "inbox-intelligence": _agent(
        "inbox-intelligence",
        "Inbox Intelligence Agent",
        "Classify supplied email content.",
        "extraction",
        ["read_supplied_email_content"],
        ["email_content", "thread_context"],
        ["classification_accuracy", "unsupported_claim_rate"],
        _grounded("Classify and summarize only supplied email content. Do not send replies."),
    ),
    "career-recommendation": _agent(
        "career-recommendation",
        "Career Recommendation Agent",
        "Recommend next career actions from supplied context.",
        "reasoning",
        ["read_supplied_career_context"],
        ["candidate_profile", "opportunities", "preferences"],
        ["recommendation_relevance", "explanation_grounding"],
        f"Make practical recommendations and explain uncertainty. {_EVIDENCE_RULE}",
    ),
    "quality-assurance-policy": _agent(
        "quality-assurance-policy",
        "Quality Assurance and Policy Agent",
        "Review supplied outputs for grounding and policy issues.",
        "reasoning",
        ["read_supplied_review_context"],
        ["draft_output", "source_evidence", "policy_context"],
        ["unsupported_claim_detection", "policy_violation_recall"],
        _grounded("Review claims against supplied evidence and flag unsupported statements."),
    ),
}


def list_agents() -> list[AgentDescriptor]:
    return [agent.descriptor for agent in AGENTS.values()]
