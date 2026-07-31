from uuid import uuid4

from fastapi.testclient import TestClient

from vav.main import app


def test_public_quote_rejects_frontend_supplied_total() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/public/catalog/pricing/quote",
            json={
                "sku_id": str(uuid4()),
                "quantity": 1,
                "requested_currency": "USD",
                "anonymous_session_id": str(uuid4()),
                "unit_amount_minor": 1,
                "total_minor": 1,
            },
        )
    assert response.status_code == 422
