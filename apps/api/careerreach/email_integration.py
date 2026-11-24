from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from email.utils import parsedate_to_datetime
from typing import cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .config import Settings
from .schemas import EmailIntegrationStatus, EmailSyncResult, SyncedEmailMessage

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)


class EmailIntegrationNotConfigured(RuntimeError):
    pass


class EmailIntegrationNotConnected(RuntimeError):
    pass


class EmailIntegrationProviderError(RuntimeError):
    pass


class InvalidEmailOAuthState(ValueError):
    pass


class EmailIntegrationService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    @property
    def configured(self) -> bool:
        try:
            self._credentials()
        except EmailIntegrationNotConfigured:
            return False
        return True

    def _credentials(self) -> tuple[str, str, str, str]:
        client_id = self._settings.google_oauth_client_id
        client_secret = self._settings.google_oauth_client_secret
        redirect_uri = self._settings.google_oauth_redirect_uri
        encryption_key = self._settings.email_token_encryption_key
        if not all((client_id, client_secret, redirect_uri, encryption_key)):
            raise EmailIntegrationNotConfigured(
                "Configure Google OAuth credentials, redirect URI, and email token encryption key."
            )
        if client_secret is None or encryption_key is None:
            raise EmailIntegrationNotConfigured("Google Mail is not configured.")
        return (
            cast(str, client_id),
            client_secret.get_secret_value(),
            cast(str, redirect_uri),
            encryption_key.get_secret_value(),
        )

    def _database_url(self) -> str:
        if self._settings.database_url is None:
            raise RuntimeError("Set CAREERREACH_DATABASE_URL to use Google Mail integration.")
        return self._settings.database_url

    async def authorization_url(self, user_id: UUID) -> str:
        client_id, _, redirect_uri, _ = self._credentials()
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            await connection.execute(
                "DELETE FROM email_oauth_state WHERE expires_at < now() OR consumed_at IS NOT NULL"
            )
            await connection.execute(
                "INSERT INTO email_oauth_state (state_hash,user_id,expires_at) "
                "VALUES (%s,%s,now()+interval '10 minutes')",
                (state_hash, user_id),
            )
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(_GOOGLE_SCOPES),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{_GOOGLE_AUTH_ENDPOINT}?{query}"

    async def complete_authorization(self, code: str, state: str) -> EmailIntegrationStatus:
        client_id, client_secret, redirect_uri, encryption_key = self._credentials()
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            cursor = await connection.execute(
                "UPDATE email_oauth_state SET consumed_at=now() "
                "WHERE state_hash=%s AND consumed_at IS NULL AND expires_at>now() "
                "RETURNING user_id",
                (state_hash,),
            )
            state_row = await cursor.fetchone()
            if state_row is None:
                raise InvalidEmailOAuthState("The email authorization state is invalid or expired.")
            user_id = cast(UUID, state_row[0])

        try:
            response = await self._client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=20.0,
            )
            response.raise_for_status()
            token_data = self._json_object(response)
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            raw_scope = token_data.get("scope", "")
            scope = raw_scope if isinstance(raw_scope, str) else ""
            if not isinstance(access_token, str):
                raise ValueError("incomplete token response")
            if not isinstance(refresh_token, str) or not refresh_token:
                raise ValueError(
                    "The provider did not issue a refresh token; reconnect with consent."
                )
            profile_response = await self._client.get(
                f"{_GMAIL_API}/profile",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15.0,
            )
            profile_response.raise_for_status()
            profile = self._json_object(profile_response)
            address = profile.get("emailAddress")
            if not isinstance(address, str) or "@" not in address:
                raise ValueError("The provider did not return a mailbox address.")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise EmailIntegrationProviderError(
                "Gmail authorization could not be completed."
            ) from exc

        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            await connection.execute(
                "INSERT INTO email_provider_integration "
                "(user_id,provider,email_address,refresh_token_ciphertext,scopes) "
                "VALUES (%s,'gmail',%s,pgp_sym_encrypt(%s,%s),%s) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "email_address=EXCLUDED.email_address,"
                "refresh_token_ciphertext=EXCLUDED.refresh_token_ciphertext,"
                "scopes=EXCLUDED.scopes,connected_at=now(),updated_at=now()",
                (user_id, address, refresh_token, encryption_key, scope.split()),
            )
        return EmailIntegrationStatus(
            configured=True,
            connected=True,
            email=address,
            scopes=scope.split(),
            message="Gmail account connected.",
        )

    async def status(self, user_id: UUID) -> EmailIntegrationStatus:
        if not self.configured:
            return EmailIntegrationStatus(
                configured=False,
                connected=False,
                message="Configure Google OAuth and email token encryption.",
            )
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT email_address,scopes FROM email_provider_integration WHERE user_id=%s",
                    (user_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            return EmailIntegrationStatus(
                configured=True,
                connected=False,
                message="Connect Gmail to continue.",
            )
        return EmailIntegrationStatus(
            configured=True,
            connected=True,
            email=row["email_address"],
            scopes=row["scopes"],
            message="Gmail is connected.",
        )

    async def disconnect(self, user_id: UUID) -> None:
        encryption_key = self._credentials()[3]
        token: str | None = None
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT pgp_sym_decrypt(refresh_token_ciphertext,%s) AS token "
                    "FROM email_provider_integration WHERE user_id=%s",
                    (encryption_key, user_id),
                )
                row = await cursor.fetchone()
                if row is not None:
                    token = row["token"]
                await cursor.execute(
                    "DELETE FROM email_provider_integration WHERE user_id=%s", (user_id,)
                )
                await cursor.execute("DELETE FROM email_message WHERE user_id=%s", (user_id,))
        if token:
            try:
                await self._client.post(
                    _GOOGLE_REVOKE_ENDPOINT, data={"token": token}, timeout=10.0
                )
            except httpx.HTTPError:
                return

    async def sync_inbox(self, user_id: UUID, max_messages: int = 500) -> EmailSyncResult:
        token, integration = await self._access_token(user_id)
        sync_after = integration["sync_after"]
        page_token = cast(str | None, integration.get("sync_page_token"))
        base_after = integration.get("sync_base_after") or sync_after
        base_after = cast(datetime | None, base_after)
        if base_after is None:
            base_after = datetime.fromtimestamp(0, UTC)
        after_seconds = max(0, int(base_after.timestamp()) - 1)
        sync_started_at = datetime.now(UTC)
        headers = {"Authorization": f"Bearer {token}"}
        messages: list[dict[str, object]] = []
        try:
            while len(messages) < max_messages:
                params: dict[str, str | int] = {
                    "maxResults": min(100, max_messages - len(messages)),
                    "q": f"after:{after_seconds} in:anywhere",
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await self._client.get(
                    f"{_GMAIL_API}/messages", params=params, headers=headers, timeout=20.0
                )
                if response.status_code == 400 and page_token is not None:
                    page_token = None
                    continue
                response.raise_for_status()
                payload = self._json_object(response)
                batch = payload.get("messages", [])
                if not isinstance(batch, list):
                    raise ValueError("invalid message list")
                messages.extend(
                    cast(dict[str, object], item)
                    for item in cast(list[object], batch)
                    if isinstance(item, dict)
                )
                next_page = payload.get("nextPageToken")
                page_token = next_page if isinstance(next_page, str) else None
                if page_token is None or not batch:
                    break
            normalized: list[dict[str, object]] = []
            for item in messages:
                message_id = item.get("id")
                if not isinstance(message_id, str):
                    continue
                detail_response = await self._client.get(
                    f"{_GMAIL_API}/messages/{message_id}",
                    params={"format": "full"},
                    headers=headers,
                    timeout=20.0,
                )
                detail_response.raise_for_status()
                normalized.append(self._parse_message(self._json_object(detail_response)))
        except (httpx.HTTPError, ValueError) as exc:
            raise EmailIntegrationProviderError("Gmail inbox synchronization failed.") from exc

        synced_at = datetime.now(UTC)
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor() as cursor:
                for message in normalized:
                    await cursor.execute(
                        "INSERT INTO email_message "
                        "(id,user_id,provider_message_id,provider_thread_id,sender,recipients,"
                        "subject,received_at,snippet,body_text,labels,synced_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (user_id,provider_message_id) DO UPDATE SET "
                        "provider_thread_id=EXCLUDED.provider_thread_id,sender=EXCLUDED.sender,"
                        "recipients=EXCLUDED.recipients,subject=EXCLUDED.subject,"
                        "received_at=EXCLUDED.received_at,snippet=EXCLUDED.snippet,"
                        "body_text=EXCLUDED.body_text,labels=EXCLUDED.labels,synced_at=EXCLUDED.synced_at",
                        (
                            uuid4(),
                            user_id,
                            message["id"],
                            message["thread_id"],
                            message["from"],
                            message["to"],
                            message["subject"],
                            message["received_at"],
                            message["snippet"],
                            message["body"],
                            message["labels"],
                            synced_at,
                        ),
                    )
                if page_token is None:
                    await cursor.execute(
                        "UPDATE email_provider_integration SET sync_after=%s,"
                        "sync_page_token=NULL,sync_base_after=NULL,updated_at=now() "
                        "WHERE user_id=%s",
                        (sync_started_at, user_id),
                    )
                else:
                    await cursor.execute(
                        "UPDATE email_provider_integration SET sync_page_token=%s,"
                        "sync_base_after=%s,updated_at=now() WHERE user_id=%s",
                        (page_token, base_after, user_id),
                    )
        return EmailSyncResult(synced_count=len(normalized), synced_at=synced_at)

    async def list_messages(self, user_id: UUID, limit: int = 100) -> list[SyncedEmailMessage]:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT provider_message_id,provider_thread_id,sender,recipients,subject,"
                    "received_at,snippet,body_text,labels FROM email_message WHERE user_id=%s "
                    "ORDER BY received_at DESC NULLS LAST LIMIT %s",
                    (user_id, limit),
                )
                rows = await cursor.fetchall()
        return [SyncedEmailMessage.model_validate(dict(row)) for row in rows]

    async def begin_campaign(self, user_id: UUID, campaign_id: UUID) -> list[UUID]:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT status FROM campaign WHERE id=%s AND user_id=%s FOR UPDATE",
                    (campaign_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise EmailIntegrationProviderError("Campaign was not found.")
                if row["status"] == "approved":
                    await cursor.execute(
                        "UPDATE campaign SET status='running',version=version+1,updated_at=now() "
                        "WHERE id=%s AND user_id=%s",
                        (campaign_id, user_id),
                    )
                    await cursor.execute(
                        "UPDATE campaign_recipient SET status='queued' "
                        "WHERE campaign_id=%s AND user_id=%s AND status='approved'",
                        (campaign_id, user_id),
                    )
                    await cursor.execute(
                        "INSERT INTO campaign_event "
                        "(id,campaign_id,user_id,from_status,to_status,actor_user_id) "
                        "VALUES (%s,%s,%s,'approved','running',%s)",
                        (uuid4(), campaign_id, user_id, user_id),
                    )
                elif row["status"] != "running":
                    raise EmailIntegrationProviderError("Campaign is not approved for execution.")
                await cursor.execute(
                    "SELECT id FROM campaign_recipient WHERE campaign_id=%s AND user_id=%s "
                    "AND status IN ('queued','sending') ORDER BY created_at,id",
                    (campaign_id, user_id),
                )
                return [cast(UUID, item["id"]) for item in await cursor.fetchall()]

    async def send_campaign_recipient(self, user_id: UUID, recipient_id: UUID) -> str:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT r.status,r.recipient_email,r.email_snapshot,r.provider_message_id,"
                    "c.status AS campaign_status FROM campaign_recipient r "
                    "JOIN campaign c ON c.id=r.campaign_id AND c.user_id=r.user_id "
                    "WHERE r.id=%s AND r.user_id=%s FOR UPDATE OF r",
                    (recipient_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise EmailIntegrationProviderError("Campaign recipient was not found.")
                status = row["status"]
                if status == "sent":
                    return "sent"
                if row["campaign_status"] != "running":
                    raise EmailIntegrationProviderError("Campaign is not running.")
                retrying = status == "sending"
                if status not in {"queued", "approved", "sending"}:
                    return cast(str, status)
                if not retrying:
                    await cursor.execute(
                        "UPDATE campaign_recipient SET status='sending',last_error=NULL "
                        "WHERE id=%s AND user_id=%s",
                        (recipient_id, user_id),
                    )
                address = cast(str, row["recipient_email"])
                email = row["email_snapshot"]
                provider_message_id = cast(str | None, row["provider_message_id"])
        access_token, integration = await self._access_token(user_id)
        message_id = provider_message_id or f"<careerreach-{recipient_id.hex}@careerreach.ai>"
        headers = {"Authorization": f"Bearer {access_token}"}
        if retrying:
            try:
                existing = await self._client.get(
                    f"{_GMAIL_API}/messages",
                    params={"q": f"rfc822msgid:{message_id.strip('<>')}", "maxResults": 1},
                    headers=headers,
                    timeout=15.0,
                )
                existing.raise_for_status()
                results = self._json_object(existing).get("messages", [])
            except (httpx.HTTPError, ValueError) as exc:
                await self._record_recipient_result(
                    user_id, recipient_id, "unknown", "Could not reconcile prior Gmail send."
                )
                raise EmailIntegrationProviderError(
                    "Gmail send status is unknown; recipient was not sent again."
                ) from exc
            if isinstance(results, list) and results:
                first = cast(object, results[0])
                gmail_id_value = (
                    cast(dict[str, object], first).get("id") if isinstance(first, dict) else None
                )
                gmail_id = gmail_id_value if isinstance(gmail_id_value, str) else None
                await self._record_recipient_result(user_id, recipient_id, "sent", None, gmail_id)
                return "sent"
            await self._record_recipient_result(
                user_id, recipient_id, "unknown", "Previous send may have completed; not retried."
            )
            return "unknown"

        account_address = cast(str, integration["email_address"])
        raw_email = cast(dict[str, object], email)
        mime = MimeMessage()
        mime["To"] = address
        mime["From"] = account_address
        mime["Subject"] = str(raw_email["subject"])
        mime["Message-ID"] = message_id
        mime.set_content(str(raw_email["body"]))
        encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii").rstrip("=")
        try:
            response = await self._client.post(
                f"{_GMAIL_API}/messages/send",
                headers=headers,
                json={"raw": encoded},
                timeout=30.0,
            )
            response.raise_for_status()
            payload = self._json_object(response)
            gmail_id = payload.get("id")
            if not isinstance(gmail_id, str):
                raise ValueError("Gmail did not return a sent message identifier.")
        except httpx.TimeoutException:
            await self._record_recipient_result(
                user_id, recipient_id, "unknown", "Gmail timed out after the send request."
            )
            return "unknown"
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                await self._record_recipient_result(
                    user_id,
                    recipient_id,
                    "queued",
                    "Gmail rate limited this request; Temporal will retry it.",
                )
                raise EmailIntegrationProviderError(
                    "Gmail rate limited campaign delivery."
                ) from exc
            await self._record_recipient_result(
                user_id, recipient_id, "failed", f"Gmail rejected the send ({status_code})."
            )
            return "failed"
        except (httpx.HTTPError, ValueError):
            await self._record_recipient_result(
                user_id, recipient_id, "unknown", "Gmail send outcome could not be confirmed."
            )
            return "unknown"
        await self._record_recipient_result(user_id, recipient_id, "sent", None, gmail_id)
        return "sent"

    async def finish_campaign(self, user_id: UUID, campaign_id: UUID) -> str:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT status FROM campaign WHERE id=%s AND user_id=%s FOR UPDATE",
                    (campaign_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise EmailIntegrationProviderError("Campaign was not found.")
                if row["status"] in {"completed", "failed", "cancelled"}:
                    return cast(str, row["status"])
                await cursor.execute(
                    "UPDATE campaign_recipient SET status='failed',last_error=COALESCE(last_error,"
                    "'Campaign execution ended before delivery.') "
                    "WHERE campaign_id=%s AND user_id=%s AND status='queued'",
                    (campaign_id, user_id),
                )
                await cursor.execute(
                    "UPDATE campaign_recipient SET status='unknown',last_error=COALESCE(last_error,"
                    "'Delivery outcome could not be confirmed.') "
                    "WHERE campaign_id=%s AND user_id=%s AND status='sending'",
                    (campaign_id, user_id),
                )
                await cursor.execute(
                    "SELECT COUNT(*) FILTER (WHERE status <> 'sent') AS outstanding "
                    "FROM campaign_recipient WHERE campaign_id=%s AND user_id=%s",
                    (campaign_id, user_id),
                )
                count = await cursor.fetchone()
                result = (
                    "completed" if count is not None and count["outstanding"] == 0 else "failed"
                )
                previous = cast(str, row["status"])
                await cursor.execute(
                    "UPDATE campaign SET status=%s,version=version+1,updated_at=now() "
                    "WHERE id=%s AND user_id=%s",
                    (result, campaign_id, user_id),
                )
                await cursor.execute(
                    "INSERT INTO campaign_event "
                    "(id,campaign_id,user_id,from_status,to_status,actor_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (uuid4(), campaign_id, user_id, previous, result, user_id),
                )
                return result

    async def integration_email(self, user_id: UUID) -> str:
        _, row = await self._access_token(user_id)
        return cast(str, row["email_address"])

    async def _access_token(self, user_id: UUID) -> tuple[str, dict[str, object]]:
        client_id, client_secret, _, encryption_key = self._credentials()
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT email_address,scopes,pgp_sym_decrypt(refresh_token_ciphertext,%s) "
                    "AS refresh_token,sync_after,sync_page_token,sync_base_after "
                    "FROM email_provider_integration WHERE user_id=%s",
                    (encryption_key, user_id),
                )
                row = await cursor.fetchone()
        if row is None:
            raise EmailIntegrationNotConnected("Connect Gmail before sending or syncing email.")
        refresh_token = cast(str, row["refresh_token"])
        try:
            response = await self._client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15.0,
            )
            response.raise_for_status()
            payload = self._json_object(response)
            access_token = payload.get("access_token")
            if not isinstance(access_token, str):
                raise ValueError("missing Google access token")
            return access_token, cast(dict[str, object], row)
        except (httpx.HTTPError, ValueError) as exc:
            raise EmailIntegrationProviderError("Google Mail token refresh failed.") from exc

    async def _record_recipient_result(
        self,
        user_id: UUID,
        recipient_id: UUID,
        status: str,
        error: str | None,
        provider_message_id: str | None = None,
    ) -> None:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._tenant(connection, user_id)
            await connection.execute(
                "UPDATE campaign_recipient SET status=%s,last_error=%s,"
                "provider_message_id=COALESCE(%s,provider_message_id) "
                "WHERE id=%s AND user_id=%s",
                (status, error, provider_message_id, recipient_id, user_id),
            )

    async def _tenant(self, connection: AsyncConnection, user_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user_id),))

    @classmethod
    def _parse_message(cls, message: dict[str, object]) -> dict[str, object]:
        payload_value = message.get("payload")
        payload = (
            cast(dict[str, object], payload_value) if isinstance(payload_value, dict) else None
        )
        header_map: dict[str, str] = {}
        if payload is not None:
            raw_headers = payload.get("headers", [])
            if isinstance(raw_headers, list):
                for header in cast(list[object], raw_headers):
                    if isinstance(header, dict):
                        header_data = cast(dict[str, object], header)
                        name = header_data.get("name")
                        value = header_data.get("value")
                        if isinstance(name, str) and isinstance(value, str):
                            header_map[name.casefold()] = value
        body_parts: list[str] = []
        if payload is not None:
            cls._collect_plain_text(payload, body_parts)
        internal_date = message.get("internalDate")
        try:
            received_at = (
                datetime.fromtimestamp(int(internal_date) / 1000, UTC)
                if isinstance(internal_date, str)
                else parsedate_to_datetime(header_map["date"]).astimezone(UTC)
            )
        except (ValueError, KeyError, OverflowError):
            received_at = None
        raw_to = header_map.get("to", "")
        raw_labels = message.get("labelIds", [])
        labels = (
            [item for item in cast(list[object], raw_labels) if isinstance(item, str)]
            if isinstance(raw_labels, list)
            else []
        )
        return {
            "id": message.get("id", ""),
            "thread_id": message.get("threadId", ""),
            "from": header_map.get("from"),
            "to": [item.strip() for item in raw_to.split(",") if item.strip()],
            "subject": header_map.get("subject"),
            "received_at": received_at,
            "snippet": str(message.get("snippet", ""))[:2_000],
            "body": "\n".join(body_parts)[:50_000],
            "labels": labels,
        }

    @classmethod
    def _collect_plain_text(cls, part: dict[str, object], output: list[str]) -> None:
        mime_type = part.get("mimeType")
        body_value = part.get("body")
        body = cast(dict[str, object], body_value) if isinstance(body_value, dict) else None
        data = body.get("data") if body is not None else None
        if mime_type == "text/plain" and isinstance(data, str):
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                output.append(decoded.decode("utf-8", errors="replace"))
            except (ValueError, binascii.Error):
                pass
        parts = part.get("parts")
        if isinstance(parts, list):
            for child in cast(list[object], parts):
                if isinstance(child, dict):
                    cls._collect_plain_text(cast(dict[str, object], child), output)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        payload: object = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Provider returned an invalid JSON object.")
        return cast(dict[str, object], payload)
