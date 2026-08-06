"""Idempotency key handling and request fingerprinting."""

from __future__ import annotations

import pytest

from vav.common.exceptions import VavError
from vav.modules.matchmaking_interactions.idempotency import (
    IdempotencyOperation,
    normalise_key,
    request_hash,
)


def test_reordered_json_is_the_same_request() -> None:
    """A client serialising its body differently is still retrying."""
    first = request_hash({"a": 1, "b": 2})
    second = request_hash({"b": 2, "a": 1})
    assert first == second


def test_a_changed_value_is_a_different_request() -> None:
    assert request_hash({"skip_type": "not_now"}) != request_hash({"skip_type": "not_interested"})


def test_a_changed_target_is_a_different_request() -> None:
    assert request_hash({"item": "a"}) != request_hash({"item": "b"})


def test_an_added_field_is_a_different_request() -> None:
    assert request_hash({"a": 1}) != request_hash({"a": 1, "b": None})


def test_a_missing_key_is_rejected() -> None:
    with pytest.raises(VavError) as excinfo:
        normalise_key(None)
    assert excinfo.value.code == "IDEMPOTENCY_KEY_REQUIRED"


def test_a_blank_key_is_rejected() -> None:
    with pytest.raises(VavError):
        normalise_key("   ")


def test_an_oversized_key_is_rejected() -> None:
    """The column is 128 characters; refusing early beats a database error."""
    with pytest.raises(VavError) as excinfo:
        normalise_key("k" * 129)
    assert excinfo.value.code == "IDEMPOTENCY_KEY_INVALID"


def test_surrounding_whitespace_is_ignored() -> None:
    assert normalise_key("  abc  ") == "abc"


def test_every_member_write_has_an_operation_name() -> None:
    """Operations are namespaced so one key can be reused across operations.

    A member's client may generate one key per gesture; scoping the record by
    operation stops a like and a skip from colliding on it.
    """
    operations = {
        value for name, value in vars(IdempotencyOperation).items() if not name.startswith("_")
    }
    expected = {
        "like",
        "skip",
        "withdraw_like",
        "withdraw_skip",
        "close_match",
        "send_invitation",
        "accept_invitation",
        "decline_invitation",
        "cancel_invitation",
        "request_contact_exchange",
        "submit_contact_consent",
        "withdraw_contact_consent",
    }
    assert operations == expected
