from typing import cast
from uuid import uuid4

import pytest
from fastapi import Request

from vav.core.database import session_factory
from vav.models.catalog import Product, ProductLocalization
from vav.models.identity import AuthSession, User
from vav.modules.catalog.router import update_product_localization
from vav.modules.catalog.schemas import ProductLocalizationUpdateRequest
from vav.modules.identity.dependencies import AuthenticatedPrincipal
from vav.modules.identity.domain import UserStatus


@pytest.mark.asyncio
async def test_localization_update_returns_fresh_product_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def skip_catalog_version_bump() -> None:
        return None

    monkeypatch.setattr(
        "vav.modules.catalog.router._bump_catalog_version",
        skip_catalog_version_bump,
    )
    suffix = uuid4().hex
    async with session_factory() as session:
        actor = User(
            email=f"catalog-localization-{suffix}@example.com",
            display_email=f"catalog-localization-{suffix}@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
        )
        session.add(actor)
        await session.flush()
        product = Product(
            product_code=f"LOC-{suffix.upper()}",
            product_type="digital_service",
            fulfillment_type="digital_access",
            internal_name="Localization integration test",
            visibility="public",
            default_locale="zh-CN",
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductLocalization(
                product_id=product.id,
                locale="zh-CN",
                slug=f"localization-{suffix}",
                name="待发布服务",
                description_blocks=[],
                translation_status="draft",
            )
        )
        await session.commit()

        principal = AuthenticatedPrincipal(
            user=actor,
            session=cast(AuthSession, None),
            audience="vav-admin",
            permissions=frozenset({"catalog.products.update"}),
        )
        request = Request({"type": "http", "headers": []})
        response = await update_product_localization(
            product_id=product.id,
            locale="zh-CN",
            payload=ProductLocalizationUpdateRequest(
                locale="zh-CN",
                slug=f"localization-{suffix}",
                name="已就绪服务",
                description_blocks=[],
                translation_status="ready",
                expected_version=1,
                reason="Verify refreshed product response after localization update.",
            ),
            request=request,
            principal=principal,
            session=session,
        )

    data = response["data"]
    assert data["version"] == 2
    assert data["updated_at"]
    assert data["localizations"]["zh-CN"]["translation_status"] == "ready"
