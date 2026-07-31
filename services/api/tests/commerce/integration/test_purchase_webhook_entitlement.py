from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from vav.core.config import get_settings
from vav.core.database import session_factory
from vav.main import app
from vav.models.catalog import (
    Price,
    PriceBook,
    Product,
    ProductLocalization,
    ProductSku,
    SupportedCurrency,
)
from vav.models.courses import (
    Course,
    CourseCompletionPolicy,
    CourseEnrollment,
    CourseInboxEvent,
    CourseVersion,
)
from vav.models.identity import AuthSession, User
from vav.modules.identity.domain import SessionStatus, UserStatus
from vav.modules.identity.security import AccessTokenService


async def commerce_fixture() -> tuple[str, ProductSku]:
    suffix = uuid4().hex
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = User(
            email=f"buyer-{suffix}@example.com",
            display_email=f"buyer-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            terms_version="test-v1",
            terms_accepted_at=now,
            privacy_version="test-v1",
            privacy_accepted_at=now,
        )
        session.add(user)
        await session.flush()
        auth_session = AuthSession(
            id=uuid4(),
            user_id=user.id,
            session_family_id=uuid4(),
            refresh_token_hash=f"test-{suffix}",
            audience=get_settings().auth_user_audience,
            status=SessionStatus.ACTIVE,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
        session.add(auth_session)
        product = Product(
            product_code=f"COMMERCE-{suffix.upper()}",
            product_type="digital_service",
            fulfillment_type="digital_access",
            internal_name="Commerce integration product",
            status="active",
            visibility="public",
            default_locale="zh-CN",
            created_by=user.id,
            updated_by=user.id,
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLocalization(
                product_id=product.id,
                locale="zh-CN",
                slug=f"commerce-{suffix}",
                name="交易集成测试服务",
                short_description="仅用于自动化测试",
                description_blocks=[],
                translation_status="ready",
            )
        )
        sku = ProductSku(
            product_id=product.id,
            sku_code=f"COMMERCE-SKU-{suffix.upper()}",
            internal_name="Commerce integration SKU",
            billing_type="one_time",
            status="active",
            fulfillment_configuration={"validity_days": 30},
            inventory_policy="unlimited",
        )
        session.add(sku)
        await session.flush()
        policy = CourseCompletionPolicy(
            policy_code=f"commerce-course-policy-{suffix}",
            policy_version=1,
            certificate_enabled=False,
        )
        session.add(policy)
        await session.flush()
        course = Course(
            course_code=f"commerce-course-{suffix}",
            internal_name="Commerce integration course",
            course_type="self_paced",
            status="published",
            visibility="private",
            default_locale="zh-CN",
            free_access_policy=None,
            catalog_product_id=product.id,
            primary_catalog_sku_id=sku.id,
            completion_policy_id=policy.id,
            created_by=user.id,
            updated_by=user.id,
        )
        session.add(course)
        await session.flush()
        session.add(
            CourseVersion(
                course_id=course.id,
                version_number=1,
                curriculum_snapshot={"schema_version": 1, "modules": []},
                change_summary="Commerce entitlement integration fixture",
                created_by=user.id,
                published_at=now,
            )
        )
        sku.fulfillment_configuration = {
            "bundle_code": f"COMMERCE-BUNDLE-{suffix}",
            "included_courses": [
                {
                    "course_id": str(course.id),
                    "course_version": 1,
                    "access_duration_days": 30,
                }
            ],
        }
        if await session.get(SupportedCurrency, "USD") is None:
            session.add(
                SupportedCurrency(currency_code="USD", exponent=2, enabled=True, display_order=10)
            )
        book = await session.scalar(
            select(PriceBook).where(PriceBook.price_book_code == "GLOBAL_STANDARD")
        )
        if book is None:
            book = PriceBook(
                price_book_code="GLOBAL_STANDARD",
                name="Global standard",
                status="active",
                priority=0,
            )
            session.add(book)
            await session.flush()
        session.add(
            Price(
                sku_id=sku.id,
                price_book_id=book.id,
                currency_code="USD",
                unit_amount_minor=2599,
                billing_type="one_time",
                valid_from=now - timedelta(minutes=1),
                status="active",
                created_by=user.id,
            )
        )
        await session.commit()
        token = AccessTokenService().issue(
            user_id=user.id,
            session_id=auth_session.id,
            audience=get_settings().auth_user_audience,
            auth_version=user.auth_version,
            rbac_version=user.rbac_version,
        )
        return token, sku


def signed_event(payload: dict[str, object]) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        get_settings().payment_test_webhook_secret.get_secret_value().encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return body, signature


@pytest.mark.asyncio
async def test_payment_requires_verified_webhook_and_activates_once() -> None:
    token, sku = await commerce_fixture()
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        cart_response = client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"sku_id": str(sku.id), "quantity": 1, "currency_code": "USD"},
        )
        assert cart_response.status_code == 201
        cart = cart_response.json()["data"]
        preview_response = client.post(
            "/api/v1/checkout/preview",
            headers=headers,
            json={"cart_id": cart["id"], "locale": "zh-CN"},
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["data"]
        order_response = client.post(
            "/api/v1/checkout/orders",
            headers={**headers, "Idempotency-Key": f"checkout-{uuid4()}"},
            json={
                "cart_id": cart["id"],
                "billing_email": "billing@example.com",
                "locale": "zh-CN",
                "expected_total_minor": preview["total_minor"],
                "terms_version": "test-v1",
                "privacy_version": "test-v1",
                "refund_policy_version": "test-v1",
            },
        )
        assert order_response.status_code == 201, order_response.text
        order = order_response.json()["data"]
        payment_response = client.post(
            f"/api/v1/orders/{order['order_number']}/payments",
            headers={**headers, "Idempotency-Key": f"payment-{uuid4()}"},
            json={"provider": "stripe"},
        )
        assert payment_response.status_code == 201, payment_response.text
        payment = payment_response.json()["data"]

        before = client.get(f"/api/v1/orders/{order['order_number']}", headers=headers).json()[
            "data"
        ]
        assert before["status"] == "payment_processing"
        assert before["entitlements"] == []

        payload = {
            "id": f"evt_test_{uuid4().hex}",
            "type": "payment.succeeded",
            "data": {
                "provider_payment_id": payment["client_action"]["url"]
                .split("provider=")[0]
                .split("never-match")[-1],
                "order_id": order["id"],
                "amount_minor": order["total_minor"],
                "currency": order["currency"],
            },
        }
        # The provider ID is intentionally not exposed in client_action; retrieve it from the DB.
        async with session_factory() as session:
            from vav.models.commerce import PaymentAttempt

            attempt = await session.get(PaymentAttempt, payment["id"])
            assert attempt is not None
            payload["data"]["provider_payment_id"] = attempt.provider_payment_id
        body, signature = signed_event(payload)
        webhook_headers = {
            "Content-Type": "application/json",
            "X-VAV-Test-Signature": signature,
        }
        first = client.post("/api/v1/webhooks/stripe", content=body, headers=webhook_headers)
        duplicate = client.post("/api/v1/webhooks/stripe", content=body, headers=webhook_headers)
        assert first.status_code == 200, first.text
        assert first.json()["data"]["status"] == "processed"
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["event_id"] == first.json()["data"]["event_id"]

        after = client.get(f"/api/v1/orders/{order['order_number']}", headers=headers).json()[
            "data"
        ]
        assert after["status"] == "fulfilled"
        assert len(after["entitlements"]) == 1
        assert after["entitlements"][0]["status"] == "active"
        async with session_factory() as session:
            enrollment = await session.scalar(
                select(CourseEnrollment).where(
                    CourseEnrollment.entitlement_id == UUID(after["entitlements"][0]["id"])
                )
            )
            assert enrollment is not None
            version = await session.get(CourseVersion, enrollment.course_version_id)
            assert version is not None
            assert version.version_number == 1
            assert enrollment.source_type == "bundle_purchase"
            inbox_count = await session.scalar(
                select(func.count())
                .select_from(CourseInboxEvent)
                .where(
                    CourseInboxEvent.event_type == "entitlement.activated",
                    CourseInboxEvent.processing_status == "processed",
                )
            )
            assert inbox_count and inbox_count >= 1
