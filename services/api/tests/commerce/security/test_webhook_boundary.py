from fastapi.testclient import TestClient

from vav.main import app


def test_unsigned_webhook_cannot_change_payment_state() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/stripe",
            json={
                "id": "evt_test_unsigned",
                "type": "payment.succeeded",
                "data": {},
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"
