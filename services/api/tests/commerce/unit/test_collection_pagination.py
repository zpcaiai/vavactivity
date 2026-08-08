from vav.modules.commerce.router import _page_payload


def test_page_payload_preserves_items_and_reports_bounded_metadata() -> None:
    payload = _page_payload(
        [{"id": "one"}, {"id": "two"}],
        page=2,
        page_size=2,
        total=5,
    )

    assert payload["items"] == [{"id": "one"}, {"id": "two"}]
    assert payload["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total": 5,
        "pages": 3,
    }


def test_commerce_collection_contracts_expose_bounded_page_parameters(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    collection_paths = {
        "/api/v1/orders",
        "/api/v1/entitlements",
        "/api/v1/subscriptions",
        "/api/v1/admin/commerce/orders",
        "/api/v1/admin/commerce/payments",
        "/api/v1/admin/commerce/subscriptions",
        "/api/v1/admin/commerce/refunds",
        "/api/v1/admin/commerce/webhooks",
        "/api/v1/admin/commerce/reconciliation",
        "/api/v1/admin/commerce/entitlements",
    }

    for path in collection_paths:
        parameters = {item["name"]: item for item in paths[path]["get"]["parameters"]}
        assert parameters["page"]["schema"]["minimum"] == 1
        assert parameters["page_size"]["schema"]["maximum"] == 200
