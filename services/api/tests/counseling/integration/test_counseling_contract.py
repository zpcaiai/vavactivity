def test_counseling_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/public/counseling/services" in paths
    assert "/api/v1/public/counseling/services/{slug}" in paths
    assert "/api/v1/public/counseling/availability" in paths
    assert "/api/v1/account/counseling/slot-holds" in paths
    assert "/api/v1/account/counseling/appointments" in paths
    assert "/api/v1/account/counseling/appointments/{appointment_id}/join" in paths
    assert "/api/v1/account/counseling/session-access/{session_id}" in paths
    assert "/api/v1/admin/counseling/services/{service_id}/publish" in paths
    assert "/api/v1/admin/counseling/appointments/{appointment_id}/transition" in paths


def test_seeded_public_service_is_scoped_and_catalog_priced(client) -> None:
    response = client.get("/api/v1/public/counseling/services/growth-support-session?locale=zh-CN")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["name"] == "关系成长支持会谈"
    assert body["duration_minutes"] == 60
    assert body["prices"][0]["unit_amount_minor"] == 4900
    assert "不替代" in body["scope_notice"]
    assert "intake_response" not in response.text
    assert "meeting_reference" not in response.text
