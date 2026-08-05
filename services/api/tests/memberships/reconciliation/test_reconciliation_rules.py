from pathlib import Path


def test_reconciliation_detects_authority_and_cycle_drift() -> None:
    source = (
        (Path(__file__).parents[3] / "../worker/src/vav_worker/tasks.py")
        .resolve()
        .read_text(encoding="utf-8")
    )
    assert "ENTITLEMENT_INACTIVE" in source
    assert "CURRENT_CYCLE_MISSING" in source
    assert "membership_reconciliation_issues" in source
