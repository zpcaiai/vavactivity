from fastapi import Response
from fastapi.testclient import TestClient

from vav.main import app
from vav.modules.identity.router import _clear_session_cookies


def test_refresh_requires_cookie_origin_and_csrf_header() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_user_and_admin_csrf_cookies_are_isolated() -> None:
    user_response = Response()
    admin_response = Response()

    _clear_session_cookies(user_response, audience="user")
    _clear_session_cookies(admin_response, audience="admin")

    user_cookies = "\n".join(user_response.headers.getlist("set-cookie"))
    admin_cookies = "\n".join(admin_response.headers.getlist("set-cookie"))
    assert "vav_user_csrf=" in user_cookies
    assert "vav_admin_csrf=" in admin_cookies
    assert "vav_admin_csrf=" not in user_cookies
    assert "vav_user_csrf=" not in admin_cookies
