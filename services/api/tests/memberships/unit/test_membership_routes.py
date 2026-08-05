from vav.main import app


def test_batch_17_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/public/membership-plans",
        "/api/v1/account/membership",
        "/api/v1/account/membership/change-preview",
        "/api/v1/internal/membership/access-decisions",
        "/api/v1/internal/membership/quota-reservations",
        "/api/v1/admin/memberships/plans",
        "/api/v1/admin/membership-plan-versions/{version_id}/activate",
        "/api/v1/admin/memberships/reconciliation",
    }
    assert required <= set(paths)
