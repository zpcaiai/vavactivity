from fastapi.testclient import TestClient

from vav.main import app


def test_refresh_requires_cookie_origin_and_csrf_header() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
