from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_UPLOAD_REQUEST_BYTES = 5 * 1024 * 1024 + 64 * 1024


class ResumeUploadLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/v1/resumes"
        ):
            await self._app(scope, receive, send)
            return
        body_parts: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body_part = message.get("body", b"")
            size += len(body_part)
            if size > MAX_UPLOAD_REQUEST_BYTES:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"detail":"Resume upload request exceeds the 5 MiB file limit."}',
                    }
                )
                return
            body_parts.append(body_part)
            if not message.get("more_body", False):
                break
        body = b"".join(body_parts)
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self._app(scope, replay_receive, send)
