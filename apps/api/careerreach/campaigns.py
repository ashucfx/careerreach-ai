from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings
from .schemas import (
    Campaign,
    CampaignCreateRequest,
    CampaignRecipient,
    CampaignSummary,
    CampaignTransitionRequest,
    OutreachEmail,
)

CampaignStatus = Literal[
    "draft",
    "awaiting_approval",
    "approved",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
]


class CampaignNotFound(LookupError):
    pass


class CampaignVersionConflict(ValueError):
    pass


class CampaignTransitionInvalid(ValueError):
    pass


class CampaignDraftNotFound(ValueError):
    pass


class CampaignService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _database_url(self) -> str:
        if self._settings.database_url is None:
            raise RuntimeError("Set CAREERREACH_DATABASE_URL to manage campaigns.")
        return self._settings.database_url

    async def create(self, user_id: UUID, request: CampaignCreateRequest) -> Campaign:
        campaign_id = uuid4()
        draft_ids = [recipient.draft_id for recipient in request.recipients]
        email_by_draft = {
            recipient.draft_id: str(recipient.recipient_email) for recipient in request.recipients
        }
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT id, version, email FROM outreach_draft "
                    "WHERE user_id=%s AND id = ANY(%s) ORDER BY created_at, id",
                    (user_id, draft_ids),
                )
                drafts = await cursor.fetchall()
                if len(drafts) != len(draft_ids):
                    raise CampaignDraftNotFound(
                        "One or more selected outreach drafts were not found."
                    )
                await cursor.execute(
                    "INSERT INTO campaign (id,user_id,name,status) "
                    "VALUES (%s,%s,%s,'draft') RETURNING created_at,updated_at",
                    (campaign_id, user_id, request.name),
                )
                campaign_row = await cursor.fetchone()
                if campaign_row is None:
                    raise RuntimeError("Campaign write did not return a record.")
                recipients: list[CampaignRecipient] = []
                for draft in drafts:
                    recipient_id = uuid4()
                    await cursor.execute(
                        "INSERT INTO campaign_recipient "
                        "(id,campaign_id,user_id,outreach_draft_id,draft_version,recipient_email,"
                        "status,email_snapshot) "
                        "VALUES (%s,%s,%s,%s,%s,%s,'pending_approval',%s) RETURNING created_at",
                        (
                            recipient_id,
                            campaign_id,
                            user_id,
                            draft["id"],
                            draft["version"],
                            email_by_draft[draft["id"]],
                            Jsonb(draft["email"]),
                        ),
                    )
                    recipient_row = await cursor.fetchone()
                    if recipient_row is None:
                        raise RuntimeError("Campaign recipient write did not return a record.")
                    recipients.append(
                        CampaignRecipient(
                            id=recipient_id,
                            draft_id=draft["id"],
                            draft_version=draft["version"],
                            recipient_email=email_by_draft[draft["id"]],
                            status="pending_approval",
                            email_snapshot=OutreachEmail.model_validate(draft["email"]),
                            created_at=cast(datetime, recipient_row["created_at"]),
                        )
                    )
                await cursor.execute(
                    "INSERT INTO campaign_event "
                    "(id,campaign_id,user_id,from_status,to_status,actor_user_id) "
                    "VALUES (%s,%s,%s,NULL,'draft',%s)",
                    (uuid4(), campaign_id, user_id, user_id),
                )
        return Campaign(
            id=campaign_id,
            name=request.name,
            status="draft",
            version=1,
            recipients=recipients,
            created_at=cast(datetime, campaign_row["created_at"]),
            updated_at=cast(datetime, campaign_row["updated_at"]),
        )

    async def list(self, user_id: UUID) -> list[CampaignSummary]:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT c.id,c.name,c.status,c.version,c.created_at,c.updated_at,c.approved_at,"
                    "COUNT(r.id)::integer AS recipient_count FROM campaign c "
                    "LEFT JOIN campaign_recipient r ON r.campaign_id=c.id AND r.user_id=c.user_id "
                    "WHERE c.user_id=%s GROUP BY c.id ORDER BY c.updated_at DESC,c.id",
                    (user_id,),
                )
                rows = await cursor.fetchall()
        return [CampaignSummary.model_validate(dict(row)) for row in rows]

    async def get(self, user_id: UUID, campaign_id: UUID) -> Campaign:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT id,name,status,version,created_at,updated_at,approved_at "
                    "FROM campaign WHERE id=%s AND user_id=%s",
                    (campaign_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CampaignNotFound("Campaign was not found.")
                await cursor.execute(
                    "SELECT id,outreach_draft_id AS draft_id,draft_version,recipient_email,status,"
                    "email_snapshot,created_at FROM campaign_recipient "
                    "WHERE campaign_id=%s AND user_id=%s ORDER BY created_at,id",
                    (campaign_id, user_id),
                )
                recipients = [
                    CampaignRecipient.model_validate(dict(item)) for item in await cursor.fetchall()
                ]
        return Campaign.model_validate({**dict(row), "recipients": recipients})

    async def submit_for_approval(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"draft"},
            target="awaiting_approval",
            recipient_target="pending_approval",
        )

    async def approve(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"awaiting_approval"},
            target="approved",
            recipient_target="approved",
        )

    async def reject(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"awaiting_approval"},
            target="draft",
            recipient_target="pending_approval",
        )

    async def pause(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"approved"},
            target="paused",
            recipient_target="approved",
        )

    async def resume(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"paused"},
            target="approved",
            recipient_target="approved",
        )

    async def cancel(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        return await self._transition(
            user_id,
            campaign_id,
            request.expected_version,
            allowed={"draft", "awaiting_approval", "approved", "paused", "running"},
            target="cancelled",
            recipient_target="cancelled",
        )

    async def retry_failed(
        self, user_id: UUID, campaign_id: UUID, request: CampaignTransitionRequest
    ) -> Campaign:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT status,version FROM campaign WHERE id=%s AND user_id=%s FOR UPDATE",
                    (campaign_id, user_id),
                )
                current = await cursor.fetchone()
                if current is None:
                    raise CampaignNotFound("Campaign was not found.")
                if current["version"] != request.expected_version:
                    raise CampaignVersionConflict("Campaign changed; reload before continuing.")
                if current["status"] != "failed":
                    raise CampaignTransitionInvalid(
                        "Only failed campaigns can return for approval."
                    )
                await cursor.execute(
                    "UPDATE campaign SET status='awaiting_approval',version=version+1,"
                    "approved_at=NULL,updated_at=now() WHERE id=%s AND user_id=%s",
                    (campaign_id, user_id),
                )
                await cursor.execute(
                    "UPDATE campaign_recipient SET status='pending_approval',last_error=NULL "
                    "WHERE campaign_id=%s AND user_id=%s AND status='failed'",
                    (campaign_id, user_id),
                )
                await cursor.execute(
                    "INSERT INTO campaign_event "
                    "(id,campaign_id,user_id,from_status,to_status,actor_user_id) "
                    "VALUES (%s,%s,%s,'failed','awaiting_approval',%s)",
                    (uuid4(), campaign_id, user_id, user_id),
                )
        return await self.get(user_id, campaign_id)

    async def _transition(
        self,
        user_id: UUID,
        campaign_id: UUID,
        expected_version: int,
        allowed: set[CampaignStatus],
        target: CampaignStatus,
        recipient_target: str,
    ) -> Campaign:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT status,version FROM campaign WHERE id=%s AND user_id=%s FOR UPDATE",
                    (campaign_id, user_id),
                )
                current = await cursor.fetchone()
                if current is None:
                    raise CampaignNotFound("Campaign was not found.")
                if current["version"] != expected_version:
                    raise CampaignVersionConflict("Campaign changed; reload before continuing.")
                old_status = cast(CampaignStatus, current["status"])
                if old_status not in allowed:
                    raise CampaignTransitionInvalid(
                        f"A campaign in '{old_status}' cannot transition to '{target}'."
                    )
                await cursor.execute(
                    "UPDATE campaign SET status=%s,version=version+1,updated_at=now(),"
                    "approved_at=CASE WHEN %s='approved' THEN now() "
                    "WHEN %s='draft' THEN NULL ELSE approved_at END "
                    "WHERE id=%s AND user_id=%s",
                    (target, target, target, campaign_id, user_id),
                )
                if recipient_target == "approved":
                    await cursor.execute(
                        "UPDATE campaign_recipient SET status=%s WHERE campaign_id=%s "
                        "AND user_id=%s AND status='pending_approval'",
                        (recipient_target, campaign_id, user_id),
                    )
                elif recipient_target == "pending_approval":
                    await cursor.execute(
                        "UPDATE campaign_recipient SET status=%s WHERE campaign_id=%s "
                        "AND user_id=%s AND status='approved'",
                        (recipient_target, campaign_id, user_id),
                    )
                elif recipient_target == "cancelled":
                    await cursor.execute(
                        "UPDATE campaign_recipient SET status=%s WHERE campaign_id=%s "
                        "AND user_id=%s AND status IN ('pending_approval','approved','queued')",
                        (recipient_target, campaign_id, user_id),
                    )
                await cursor.execute(
                    "INSERT INTO campaign_event "
                    "(id,campaign_id,user_id,from_status,to_status,actor_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (uuid4(), campaign_id, user_id, old_status, target, user_id),
                )
        return await self.get(user_id, campaign_id)

    async def _tenant(self, connection: AsyncConnection, user_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user_id),))
