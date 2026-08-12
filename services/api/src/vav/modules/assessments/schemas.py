"""Request payloads for the paid assessment framework (B17)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductRequest(_Base):
    """A catalogue entry. ``*_code`` fields are identifiers, not display copy."""

    product_code: Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]
    title_code: Annotated[str, Field(min_length=2, max_length=128)]
    category_code: Annotated[str, Field(min_length=2, max_length=64)]
    refund_window_hours: Annotated[int, Field(ge=0, le=8760)] = 72


class VersionRequest(_Base):
    """Create a draft version.

    The licence fields are accepted at draft time but only *enforced* at
    publication, so an editor can start authoring before the contract number
    lands — they just cannot ship it (ASSESS-001).
    """

    semantic_version: Annotated[str, Field(min_length=1, max_length=32)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=64)]
    content_source: Literal[
        "administrator_authored", "licensed_third_party", "public_domain", "partner_supplied"
    ]
    license_reference: Annotated[str, Field(max_length=255)] | None = None
    licensor_name: Annotated[str, Field(max_length=255)] | None = None
    price_minor_units: Annotated[int, Field(ge=0, le=100_000_00)]
    currency: Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")] = "CNY"


class LicenseVerificationRequest(_Base):
    """Record that a named administrator checked the licence."""

    license_reference: Annotated[str, Field(min_length=3, max_length=255)]
    licensor_name: Annotated[str, Field(max_length=255)] | None = None
    note: Annotated[str, Field(max_length=1000)] | None = None


class VersionQuestionRequest(_Base):
    """Administrator-supplied item. No licensed instrument ships here."""

    question_code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    dimension_code: Annotated[str, Field(min_length=1, max_length=64)]
    prompt_text: Annotated[str, Field(min_length=1, max_length=2000)]
    weight: Annotated[int, Field(ge=1, le=10)] = 1
    scale_min: Annotated[int, Field(ge=1, le=9)] = 1
    scale_max: Annotated[int, Field(ge=2, le=10)] = 5
    reverse_scored: bool = False
    position: Annotated[int, Field(ge=0, le=999)] = 0


class PurchaseRequest(_Base):
    """Buy one exact version. ``version_id`` is never resolved to "latest"."""

    version_id: UUID
    order_id: Annotated[str, Field(min_length=1, max_length=128)]
    quoted_price_minor_units: Annotated[int, Field(ge=0)]


class AttemptAnswersRequest(_Base):
    answers: dict[Annotated[str, Field(max_length=64)], int]
    submit: bool = False


class RefundRequest(_Base):
    """Refund / revocation. See ``domain.plan_revocation`` for the policy."""

    trigger: Literal[
        "member_request", "payment_reversal", "admin_goodwill", "license_withdrawn"
    ]
    reason: Annotated[str, Field(max_length=1000)] | None = None
    #: Required to refund a purchase whose report has already been delivered.
    admin_override: bool = False


class AdviceRequest(_Base):
    body: Annotated[str, Field(min_length=1, max_length=20000)]
    model_code: Annotated[str, Field(min_length=1, max_length=64)]
    prompt_version: Annotated[str, Field(min_length=1, max_length=64)]
    disclaimer_code: Annotated[str, Field(max_length=128)] = "assessment_ai_advice"
