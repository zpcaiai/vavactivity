from typing import Any

from fastapi.testclient import TestClient

from vav.core.logging import redact_sensitive


def test_metrics_use_route_templates_not_user_identifiers(client: TestClient) -> None:
    client.get("/api/v1/health/live")
    response = client.get("/api/v1/health/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert 'route="/api/v1/health/live"' in response.text


def test_structured_log_redaction_is_recursive() -> None:
    event: dict[str, Any] = {
        "event": "provider_failed",
        "email": "member@example.com",
        "nested": {"access_token": "raw", "safe_code": "TIMEOUT"},
    }
    redacted = redact_sensitive(None, "info", event)
    assert redacted["email"] == "[REDACTED]"
    assert redacted["nested"] == {"access_token": "[REDACTED]", "safe_code": "TIMEOUT"}
