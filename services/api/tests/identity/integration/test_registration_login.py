from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient

from vav.main import app
from vav.modules.identity.router import email_service, identity_service


def test_registration_verification_login_and_refresh(monkeypatch: object) -> None:
    captured_links: list[str] = []

    async def capture_link(**kwargs: str) -> None:
        captured_links.append(kwargs["link"])

    monkeypatch.setattr(email_service, "send_link", capture_link)  # type: ignore[attr-defined]
    email = f"identity-{uuid4()}@example.com"
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "a thoughtful passphrase",
                "preferred_locale": "zh-CN",
                "timezone": "Asia/Shanghai",
                "terms_version": "2026-07-01",
                "privacy_version": "2026-07-01",
            },
        )
        assert registration.status_code == 202
        assert registration.json()["data"]["registration_status"] == "verification_required"
        assert email not in registration.text
        assert len(captured_links) == 1

        token_match = re.search(r"token=([^&]+)", captured_links[0])
        assert token_match is not None
        token = token_match.group(1)
        verification = client.post("/api/v1/auth/email-verification/confirm", json={"token": token})
        assert verification.status_code == 200
        assert (
            client.post(
                "/api/v1/auth/email-verification/confirm", json={"token": token}
            ).status_code
            == 400
        )

        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": "a thoughtful passphrase",
                "device_name": "Test browser",
            },
        )
        assert login.status_code == 200
        access_token = login.json()["data"]["access_token"]
        assert access_token
        csrf = client.cookies["vav_user_csrf"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me.status_code == 200
        assert me.json()["data"]["email"] == email

        refresh = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "http://localhost:5173", "X-CSRF-Token": csrf},
        )
        assert refresh.status_code == 200
        assert refresh.json()["data"]["access_token"] != access_token


def test_password_forgot_response_does_not_enumerate_accounts() -> None:
    with TestClient(app) as client:
        unknown = client.post(
            "/api/v1/auth/password/forgot",
            json={"email": f"unknown-{uuid4()}@example.com"},
        )
        assert unknown.status_code == 202
        assert "eligible" in unknown.json()["data"]["message"]


def test_staging_policy_can_activate_an_existing_pending_registration(
    monkeypatch: object,
) -> None:
    async def discard_link(**kwargs: str) -> None:
        del kwargs

    monkeypatch.setattr(email_service, "send_link", discard_link)  # type: ignore[attr-defined]
    email = f"no-verification-{uuid4()}@example.com"
    password = "a thoughtful passphrase"
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "preferred_locale": "zh-CN",
                "timezone": "Asia/Shanghai",
                "terms_version": "2026-07-01",
                "privacy_version": "2026-07-01",
            },
        )
        assert registration.status_code == 202
        assert registration.json()["data"]["registration_status"] == "verification_required"

        monkeypatch.setattr(identity_service.settings, "auth_email_verification_required", False)  # type: ignore[attr-defined]
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password, "device_name": "Test browser"},
        )

        assert login.status_code == 200
        assert login.json()["data"]["user"]["email_verified"] is True
