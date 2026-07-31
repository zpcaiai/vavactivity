from uuid import uuid4

import pytest
from pydantic import ValidationError

from vav.modules.catalog.domain import ProductType, validate_fulfillment
from vav.modules.catalog.schemas import ProductCreateRequest


def test_activity_fulfillment_requires_activity_reference() -> None:
    with pytest.raises(ValidationError):
        validate_fulfillment(ProductType.ACTIVITY_TICKET, {"ticket_type": "general"})

    activity_id = uuid4()
    assert validate_fulfillment(
        ProductType.ACTIVITY_TICKET,
        {"activity_id": str(activity_id), "ticket_type": "general"},
    ) == {"activity_id": str(activity_id), "ticket_type": "general"}


def test_membership_configuration_is_validated() -> None:
    with pytest.raises(ValidationError):
        validate_fulfillment(ProductType.MEMBERSHIP, {"duration_days": 365})


def test_product_rejects_incompatible_fulfillment_type() -> None:
    with pytest.raises(ValidationError, match="fulfillment type is incompatible"):
        ProductCreateRequest.model_validate(
            {
                "product_code": "ACTIVITY-TEST",
                "product_type": "activity_ticket",
                "fulfillment_type": "digital_access",
                "internal_name": "Activity",
                "localizations": [
                    {
                        "locale": "zh-CN",
                        "slug": "activity-test",
                        "name": "活动",
                    }
                ],
            }
        )
