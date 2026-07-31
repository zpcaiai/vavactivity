def test_activity_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    required = {
        "/api/v1/activities",
        "/api/v1/activities/{slug}",
        "/api/v1/activities/{activity_id}/ticket-types",
        "/api/v1/activities/{activity_id}/registrations",
        "/api/v1/account/activity-registrations/{registration_id}/cancel",
        "/api/v1/account/activity-waitlist",
        "/api/v1/account/activities/{activity_id}/group",
        "/api/v1/account/activities/{activity_id}/participants",
        "/api/v1/account/activities/{activity_id}/choices",
        "/api/v1/account/activity-mutual-choices",
        "/api/v1/admin/activities/{activity_id}/waitlist",
        "/api/v1/admin/activities/{activity_id}/attendance",
        "/api/v1/admin/activity-checkins",
        "/api/v1/admin/activities/{activity_id}/grouping-plans",
        "/api/v1/admin/activity-grouping-plans/{plan_id}/lock",
        "/api/v1/admin/activities/{activity_id}/post-event/analytics",
    }
    assert required <= set(paths)


def test_public_activity_payload_never_uses_private_location_column_names(client) -> None:
    response = client.get("/api/v1/activities?locale=zh-CN")
    assert response.status_code == 200
    body = response.text
    assert "address_line_1_encrypted" not in body
    assert "online_join_url_encrypted" not in body
    assert '"address_line_1"' not in body
    assert '"online_join_url"' not in body


def test_ordinary_admin_contract_has_no_one_sided_choice_listing(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/admin/activity-post-event-choices" not in paths
