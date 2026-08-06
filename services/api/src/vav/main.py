from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vav.api.errors import install_exception_handlers
from vav.api.router import api_router
from vav.core.config import get_settings
from vav.core.database import close_resources
from vav.core.logging import configure_logging
from vav.core.metrics import MetricsMiddleware
from vav.core.request_context import RequestContextMiddleware
from vav.core.security_headers import SecurityHeadersMiddleware
from vav.core.telemetry import configure_telemetry
from vav.modules.content.seo import seo_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_resources()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title="VAV Platform API",
        summary="VAV 婚恋智能服务平台 API",
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
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
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    install_exception_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    application.include_router(seo_router)
    configure_telemetry(application, settings)
    return application


app = create_app()
