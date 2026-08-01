from fastapi.testclient import TestClient


def test_ai_user_contract_is_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/ai/conversations" in paths
    assert "/api/v1/ai/conversations/{conversation_id}" in paths
    assert "/api/v1/ai/conversations/{conversation_id}/messages" in paths
    assert "/api/v1/ai/conversations/{conversation_id}/memory-consent" in paths
    assert "/api/v1/ai/referrals" in paths
    assert "/api/v1/ai/messages/{message_id}/feedback" in paths
    assert "/api/v1/admin/ai/conversations" in paths
    assert "/api/v1/admin/ai/conversations/{conversation_id}/sensitive-view" in paths
    assert "/api/v1/admin/ai/referrals" in paths
    assert "/api/v1/admin/ai/prompts" in paths
    assert "/api/v1/admin/ai/models" in paths
    assert "/api/v1/admin/ai/tools" in paths
    assert "/api/v1/admin/ai/evaluation-runs" in paths
    assert "/api/v1/admin/ai/audit" in paths


def test_ai_user_endpoints_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/ai/conversations")
    assert response.status_code == 401
    assert "content_encrypted" not in response.text
    assert "internal_context_encrypted" not in response.text
    admin_response = client.get("/api/v1/admin/ai/conversations")
    assert admin_response.status_code == 401
