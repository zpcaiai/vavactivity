from datetime import UTC, datetime, timedelta

import pytest

from vav.common.exceptions import VavError
from vav.modules.admin_platform.domain import (
    mask_value,
    step_up_current,
    validate_command,
    validate_query,
)


def test_write_capabilities_require_safe_registered_commands() -> None:
    with pytest.raises(VavError, match="domain command"):
        validate_command(None, "repair")
    with pytest.raises(VavError, match="Unsafe"):
        validate_command("commerce.mark_paid", "repair")
    validate_command("commerce.reconcile_entitlement", "repair")


def test_masking_rules_are_deterministic() -> None:
    assert mask_value("private@example.com", "partial_email") == "p***@example.com"
    assert mask_value("+886900000000", "partial_phone") == "+88******000"
    assert mask_value("sensitive narrative", "redacted_text") == "[REDACTED]"


def test_query_schema_rejects_unregistered_fields() -> None:
    definition = {
        "filter_schema": {"fields": ["status"]},
        "sort_schema": {"fields": ["created_at"]},
        "column_schema": {"fields": ["status"]},
    }
    validate_query(definition, {"status": "open"}, "created_at", ["status"])
    with pytest.raises(VavError, match="unregistered"):
        validate_query(definition, {"private_notes": "x"}, "created_at", ["status"])


def test_step_up_authentication_expires() -> None:
    assert step_up_current(datetime.now(UTC) - timedelta(minutes=2))
    assert not step_up_current(datetime.now(UTC) - timedelta(hours=1))
