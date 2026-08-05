from pathlib import Path


def test_quota_reservation_uses_atomic_database_predicate() -> None:
    source = (Path(__file__).parents[3] / "src/vav/modules/memberships/quota.py").read_text(
        encoding="utf-8"
    )
    assert "FOR UPDATE" in source
    assert (
        "allocated_quantity+rollover_quantity-consumed_quantity-reserved_quantity >= :quantity"
        in source
    )
    assert "ON CONFLICT (quota_bucket_id,idempotency_key) DO NOTHING" in source
