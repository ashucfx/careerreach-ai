from uuid import uuid4

import pytest
from careerreach.schemas import CampaignCreateRequest
from pydantic import ValidationError


def test_campaign_requires_a_manual_email_for_each_draft() -> None:
    draft_id = uuid4()
    request = CampaignCreateRequest(
        name="Backend recruiter outreach",
        recipients=[{"draft_id": draft_id, "recipient_email": "recruiter@example.com"}],
    )

    assert request.recipients[0].draft_id == draft_id
    assert str(request.recipients[0].recipient_email) == "recruiter@example.com"


def test_campaign_rejects_duplicate_drafts() -> None:
    draft_id = uuid4()
    with pytest.raises(ValidationError, match="campaign draft IDs must be unique"):
        CampaignCreateRequest(
            name="Duplicate recipients",
            recipients=[
                {"draft_id": draft_id, "recipient_email": "one@example.com"},
                {"draft_id": draft_id, "recipient_email": "two@example.com"},
            ],
        )


def test_campaign_rejects_invalid_recipient_email() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(
            name="Invalid address",
            recipients=[{"draft_id": uuid4(), "recipient_email": "not-an-address"}],
        )
