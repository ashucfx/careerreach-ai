import pytest
from careerreach.inbox_intelligence import InboxEvidenceError, InboxIntelligenceService
from careerreach.schemas import InboxClassification, InboxFeedbackRequest
from pydantic import ValidationError


def test_inbox_classification_requires_evidence_from_the_message() -> None:
    classification = InboxClassification(
        category="positive_interest",
        confidence=0.92,
        summary="The recruiter wants to schedule a call.",
        urgency="normal",
        suggested_next_step="Review the message and decide whether to respond.",
        evidence_quotes=["Could you share a few times for a call?"],
    )

    InboxIntelligenceService._validate_evidence(
        classification, "Could you share a few times for a call?"
    )

    with pytest.raises(InboxEvidenceError, match="absent from the email"):
        InboxIntelligenceService._validate_evidence(classification, "Thank you for applying.")


def test_inbox_classification_rejects_unsupported_categories() -> None:
    with pytest.raises(ValidationError):
        InboxClassification(
            category="send_reply",
            confidence=0.9,
            summary="Reply requested.",
            urgency="high",
            suggested_next_step="Reply.",
            evidence_quotes=["Please reply"],
        )


def test_inbox_feedback_accepts_only_known_outcomes() -> None:
    feedback = InboxFeedbackRequest(category="referral", note="They introduced a colleague.")

    assert feedback.category == "referral"
    with pytest.raises(ValidationError):
        InboxFeedbackRequest(category="unknown_external_action")
