from fastapi.testclient import TestClient

from vav.main import app


def test_api_responses_include_baseline_security_headers() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_non_production_robots_fails_closed() -> None:
    with TestClient(app) as client:
        response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"
