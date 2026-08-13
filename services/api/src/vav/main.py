from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from vav.api.errors import install_exception_handlers
from vav.api.router import api_router
from vav.core.config import get_settings
from vav.core.database import close_resources
from vav.core.http_hardening import RequestBodyLimitMiddleware
from vav.core.logging import configure_logging
from vav.core.metrics import MetricsMiddleware
from vav.core.request_context import RequestContextMiddleware
from vav.core.security_headers import SecurityHeadersMiddleware
from vav.core.telemetry import configure_telemetry
from vav.modules.content.seo import seo_router
from vav.modules.discovery.transport import (
    install_geocode_transport,
    uninstall_geocode_transport,
)

MAX_REQUEST_BODY_BYTES = 16 * 1024 * 1024


def documentation_urls(environment: str) -> dict[str, str | None]:
    if environment in {"production", "dr"}:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Wire the map-provider HTTP transport. Without this the geocode adapters
    # have no way out to the network and every lookup degrades to "keep the
    # typed address" — correct, but silently useless (MAP-001).
    install_geocode_transport()
    try:
        yield
    finally:
        uninstall_geocode_transport()
        await close_resources()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    documentation = documentation_urls(settings.environment)
    application = FastAPI(
        title="VAV Platform API",
        summary="VAV 婚恋智能服务平台 API",
        version=settings.version,
        docs_url=documentation["docs_url"],
        redoc_url=documentation["redoc_url"],
        openapi_url=documentation["openapi_url"],
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.environment in {"production", "dr"},
    )
    install_exception_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    application.include_router(seo_router)
    configure_telemetry(application, settings)
    return application


app = create_app()
