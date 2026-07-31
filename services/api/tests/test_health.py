from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from vav.main import app


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    request_id = response.json()["meta"]["request_id"]
    assert response.headers["X-Request-ID"] == request_id
    UUID(request_id)


def test_browser_preflight_accepts_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_readiness_reports_dependencies(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    async def healthy() -> None:
        return None

    target = "vav.modules.health.router"
    monkeypatch.setattr(f"{target}.check_database", healthy)
    monkeypatch.setattr(f"{target}.check_redis", healthy)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ok",
        "dependencies": {"postgresql": "ok", "redis": "ok"},
    }


def test_readiness_fails_closed(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    async def healthy() -> None:
        return None

    async def unavailable() -> None:
        raise ConnectionError

    target = "vav.modules.health.router"
    monkeypatch.setattr(f"{target}.check_database", healthy)
    monkeypatch.setattr(f"{target}.check_redis", unavailable)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "unavailable"
    assert response.json()["data"]["dependencies"]["redis"] == "unavailable"


def test_dependencies_reopen_across_application_lifespans() -> None:
    for _ in range(2):
        with TestClient(app) as lifespan_client:
            response = lifespan_client.get("/api/v1/health/ready")
            assert response.status_code == 200
