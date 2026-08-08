from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from vav.core.http_hardening import RequestBodyLimitMiddleware
from vav.core.security_headers import SecurityHeadersMiddleware
from vav.main import documentation_urls


def test_production_documentation_is_not_publicly_routed() -> None:
    assert documentation_urls("production") == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    assert documentation_urls("dr")["openapi_url"] is None
    assert documentation_urls("staging")["openapi_url"] == "/openapi.json"


def test_sensitive_responses_are_not_cacheable_and_production_uses_hsts() -> None:
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware, hsts=True)

    @application.get("/api/v1/admin/example")
    async def sensitive() -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(application).get("/api/v1/admin/example")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_request_body_limit_rejects_oversized_payload_before_handler() -> None:
    application = FastAPI()
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)
    called = False

    @application.post("/payload")
    async def payload(request: Request) -> dict[str, int]:
        nonlocal called
        called = True
        return {"size": len(await request.body())}

    response = TestClient(application).post(
        "/payload", content=b"12345", headers={"content-type": "application/octet-stream"}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"
    assert called is False


def test_request_body_limit_allows_payload_at_boundary() -> None:
    application = FastAPI()
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)

    @application.post("/payload")
    async def payload(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(application).post(
        "/payload", content=b"1234", headers={"content-type": "application/octet-stream"}
    )

    assert response.status_code == 200
    assert response.json() == {"size": 4}


def test_request_body_limit_rejects_chunked_payload_without_content_length() -> None:
    application = FastAPI()
    application.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)

    @application.post("/payload")
    async def payload(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(application)
    with client.stream(
        "POST",
        "/payload",
        content=iter((b"12", b"345")),
        headers={"content-type": "application/octet-stream"},
    ) as response:
        assert response.status_code == 413
