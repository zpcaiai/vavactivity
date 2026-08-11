def test_admin_user_management_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/admin/users" in paths
    assert "/api/v1/admin/users/{user_id}" in paths
    assert "/api/v1/admin/users/{user_id}/suspend" in paths
    assert "/api/v1/admin/users/{user_id}/restore" in paths
    assert "/api/v1/admin/users/{user_id}/deactivate" in paths
    assert "/api/v1/admin/users/{user_id}/sessions/revoke" in paths
    assert "/api/v1/admin/users/{user_id}/history" in paths

    assert "patch" in paths["/api/v1/admin/users/{user_id}"]

    assert "/api/v1/admin/admins" in paths
    assert "/api/v1/admin/admins/invitations" in paths
    assert "/api/v1/admin/admins/invitations/{invitation_id}/revoke" in paths
    assert "/api/v1/admin/admins/{user_id}/disable" in paths
    assert "/api/v1/admin/admins/{user_id}/restore" in paths
    assert "/api/v1/admin/users/{user_id}/roles" in paths
    assert "/api/v1/admin/users/{user_id}/roles/{role_code}" in paths
