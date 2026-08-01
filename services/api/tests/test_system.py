import json

from fastapi.testclient import TestClient

from vav.core.config import get_settings


def test_version_is_enveloped(client: TestClient) -> None:
    response = client.get("/api/v1/system/version")
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "vav-platform-api"
    assert response.json()["data"]["version"]


def test_public_config_excludes_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/system/config")
    serialized = json.dumps(response.json()).lower()
    assert response.status_code == 200
    assert "database_url" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized
    assert response.json()["data"]["features"]["ai_assistant"] is get_settings().ai_enabled


def test_not_found_uses_standard_error(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["meta"]["request_id"]
