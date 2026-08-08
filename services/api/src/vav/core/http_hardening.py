"""HTTP boundary controls that apply before requests reach business handlers."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    """Reject oversized declared or streamed HTTP request bodies.

    Object uploads use presigned storage URLs in this platform, so the API can
    keep a conservative process-wide limit without buffering media in memory.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                await self._reject(scope, send, "Invalid Content-Length header.")
                return
            if declared_length < 0:
                await self._reject(scope, send, "Invalid Content-Length header.")
                return
            if declared_length > self.max_bytes:
                await self._reject(scope, send, "Request body exceeds the configured limit.")
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Request body exceeds the configured limit.",
                    )
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send, detail: str) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REQUEST_BODY_TOO_LARGE",
                    "message": detail,
                    "details": [],
                }
            },
        )

        async def disconnected() -> Message:
            return {"type": "http.disconnect"}

        await response(scope, disconnected, send)
