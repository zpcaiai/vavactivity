from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import UUID, uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="unavailable")


def normalize_request_id(value: str | None) -> str:
    if not value or len(value) > 64:
        return str(uuid4())
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid4())


def request_id_from_request(request: Request) -> str:
    return getattr(request.state, "request_id", request_id_var.get())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        token: Token[str] = request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()
            request_id_var.reset(token)
