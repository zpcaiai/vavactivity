from fastapi.testclient import TestClient

from vav.main import app


def test_public_settings_contain_only_public_allowlisted_values() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/public/site-settings")

    assert response.status_code == 200
    serialized = response.text.casefold()
    assert "database_url" not in serialized
    assert "private_key" not in serialized
    assert "token_pepper" not in serialized
    assert "launch_language_decision" not in serialized
