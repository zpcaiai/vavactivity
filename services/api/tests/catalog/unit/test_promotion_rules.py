from uuid import uuid4

from vav.modules.catalog.domain import (
    PromotionApplicationMode,
    PromotionBenefits,
    PromotionCandidate,
    PromotionContext,
    PromotionRules,
    PromotionType,
    Stackability,
    apply_promotions,
)


def candidate(
    promotion_type: PromotionType,
    benefits: PromotionBenefits,
    *,
    priority: int = 0,
    stackability: Stackability = Stackability.STACKABLE,
) -> PromotionCandidate:
    return PromotionCandidate(
        id=uuid4(),
        code=f"PROMO-{priority}-{promotion_type}",
        promotion_type=promotion_type,
        application_mode=PromotionApplicationMode.AUTOMATIC,
        priority=priority,
        stackability=stackability,
        rules=PromotionRules(),
        benefits=benefits,
    )


def context(*, subtotal: int = 1999, quantity: int = 1) -> PromotionContext:
    return PromotionContext(
        product_id=uuid4(),
        sku_id=uuid4(),
        category_id=None,
        currency="USD",
        subtotal_minor=subtotal,
        quantity=quantity,
    )


def test_percentage_fixed_amount_and_stable_stack_order() -> None:
    promotions = [
        candidate(
            PromotionType.FIXED_AMOUNT,
            PromotionBenefits(amounts={"USD": 100}),
            priority=10,
        ),
        candidate(
            PromotionType.PERCENTAGE,
            PromotionBenefits(percentage_basis_points=1500),
            priority=20,
        ),
    ]
    applied, total = apply_promotions(promotions, context())
    assert [item.discount_type for item in applied] == [
        PromotionType.PERCENTAGE,
        PromotionType.FIXED_AMOUNT,
    ]
    assert total == 400


def test_fixed_price_and_discount_floor() -> None:
    fixed_price = candidate(
        PromotionType.FIXED_PRICE,
        PromotionBenefits(fixed_prices={"USD": 999}),
    )
    fixed_amount = candidate(
        PromotionType.FIXED_AMOUNT,
        PromotionBenefits(amounts={"USD": 800}),
    )
    _, fixed_price_total = apply_promotions([fixed_price], context(subtotal=1200))
    _, capped_total = apply_promotions([fixed_amount], context(subtotal=500))
    assert fixed_price_total == 201
    assert capped_total == 500


def test_exclusive_high_priority_promotion_blocks_stacking() -> None:
    exclusive = candidate(
        PromotionType.FIXED_AMOUNT,
        PromotionBenefits(amounts={"USD": 300}),
        priority=100,
        stackability=Stackability.EXCLUSIVE,
    )
    second = candidate(
        PromotionType.FIXED_AMOUNT,
        PromotionBenefits(amounts={"USD": 200}),
        priority=10,
    )
    applied, total = apply_promotions([second, exclusive], context(subtotal=1000))
    assert len(applied) == 1
    assert total == 300


def test_free_item_discount_based_on_quantity() -> None:
    free_item = candidate(
        PromotionType.FREE_ITEM,
        PromotionBenefits(amounts={"USD": 1}),
    )
    applied, total = apply_promotions([free_item], context(subtotal=6000, quantity=3))
    assert len(applied) == 1
    assert applied[0].discount_type == PromotionType.FREE_ITEM
    assert applied[0].discount_amount_minor == 2000
    assert total == 2000


def test_free_item_more_than_quantity_is_clamped_to_quantity() -> None:
    free_item = candidate(
        PromotionType.FREE_ITEM,
        PromotionBenefits(amounts={"USD": 8}),
    )
    applied, total = apply_promotions([free_item], context(subtotal=5000, quantity=3))
    assert len(applied) == 1
    assert applied[0].discount_amount_minor == 4998
    assert total == 4998
