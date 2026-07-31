from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from vav.common.exceptions import VavError
from vav.core.request_context import request_id_from_request

logger = structlog.get_logger(__name__)


def error_body(
    request: Request,
    code: str,
    message: str,
    details: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        },
        "meta": {"request_id": request_id_from_request(request)},
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(VavError)
    async def handle_vav_error(request: Request, exc: VavError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(request, "VALIDATION_ERROR", "Invalid request", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "Resource not found" if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, code, message),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            request_id=request_id_from_request(request),
            exception_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=error_body(
                request,
                "INTERNAL_ERROR",
                "An unexpected error occurred",
            ),
        )
