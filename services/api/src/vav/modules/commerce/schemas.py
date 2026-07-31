from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, PositiveInt, model_validator


class CartItemCreateRequest(BaseModel):
    sku_id: UUID
    quantity: PositiveInt = 1
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    coupon_code: str | None = Field(default=None, min_length=2, max_length=128)
    anonymous_session_id: UUID | None = None


class CartItemUpdateRequest(BaseModel):
    quantity: PositiveInt
    coupon_code: str | None = Field(default=None, min_length=2, max_length=128)
    expected_version: int = Field(ge=1)


class CartOwnerRequest(BaseModel):
    anonymous_session_id: UUID | None = None
    currency_code: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class CheckoutPreviewRequest(BaseModel):
    cart_id: UUID
    anonymous_session_id: UUID | None = None
    locale: str = "zh-CN"
    region_code: str | None = Field(default=None, max_length=64)


class CheckoutOrderRequest(CheckoutPreviewRequest):
    billing_email: EmailStr
    billing_name: str | None = Field(default=None, max_length=200)
    expected_total_minor: int | None = Field(default=None, ge=0)
    terms_version: str = Field(min_length=1, max_length=64)
    privacy_version: str = Field(min_length=1, max_length=64)
    refund_policy_version: str = Field(min_length=1, max_length=64)


class PaymentCreateRequest(BaseModel):
    provider: Literal["stripe", "paypal"]


class OrderCancelRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class SubscriptionCancelRequest(BaseModel):
    immediate: bool = False
    reason: str = Field(min_length=10, max_length=2000)


class RefundRequestCreate(BaseModel):
    order_id: UUID
    amount_minor: int = Field(gt=0)
    reason_code: str = Field(min_length=2, max_length=128)
    reason: str = Field(min_length=10, max_length=2000)


class RefundActionRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class EntitlementConsumeRequest(BaseModel):
    quantity: PositiveInt
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=255)


class EntitlementActionRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class ReconciliationResolveRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class TestWebhookEvent(BaseModel):
    id: str = Field(min_length=3, max_length=255)
    type: str = Field(min_length=3, max_length=255)
    data: dict[str, object]

    @model_validator(mode="after")
    def require_test_namespace(self) -> TestWebhookEvent:
        if not self.id.startswith("evt_test_"):
            raise ValueError("test event IDs must use the evt_test_ prefix")
        return self
