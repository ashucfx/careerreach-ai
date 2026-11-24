from __future__ import annotations

import base64
from datetime import UTC, datetime

from careerreach.email_integration import EmailIntegrationService


def test_gmail_message_parser_extracts_headers_and_plain_text() -> None:
    encoded_body = base64.urlsafe_b64encode(b"Hello from Gmail").decode().rstrip("=")
    parsed = EmailIntegrationService._parse_message(
        {
            "id": "gmail-message-id",
            "threadId": "gmail-thread-id",
            "internalDate": "1795550400000",
            "snippet": "Hello from Gmail",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "From", "value": "Recruiter <recruiter@example.com>"},
                    {"name": "To", "value": "candidate@example.com"},
                    {"name": "Subject", "value": "Next steps"},
                ],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": "PGI+SGlkZGVuPC9iPg"},
                    },
                    {"mimeType": "text/plain", "body": {"data": encoded_body}},
                ],
            },
        }
    )

    assert parsed["id"] == "gmail-message-id"
    assert parsed["thread_id"] == "gmail-thread-id"
    assert parsed["from"] == "Recruiter <recruiter@example.com>"
    assert parsed["to"] == ["candidate@example.com"]
    assert parsed["subject"] == "Next steps"
    assert parsed["body"] == "Hello from Gmail"
    assert parsed["labels"] == ["INBOX", "UNREAD"]
    assert parsed["received_at"] == datetime.fromtimestamp(1795550400, UTC)


def test_gmail_message_parser_tolerates_missing_or_malformed_parts() -> None:
    parsed = EmailIntegrationService._parse_message(
        {
            "id": "minimal-message",
            "threadId": "minimal-thread",
            "payload": {
                "headers": [{"name": "Date", "value": "not a date"}],
                "parts": [{"mimeType": "text/plain", "body": {"data": "***"}}],
            },
        }
    )

    assert parsed["id"] == "minimal-message"
    assert parsed["body"] == ""
    assert parsed["received_at"] is None
