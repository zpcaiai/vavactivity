from __future__ import annotations

import pytest

from vav_skill_runtime.security import (
    EgressDestination,
    EgressPolicy,
    SecretBroker,
    SecurityPolicyError,
    TemporarySecretHandle,
)


def test_egress_allows_only_https_allowlist_with_public_dns() -> None:
    policy = EgressPolicy(
        [EgressDestination("api.example.com", frozenset({443}))],
        resolver=lambda _host: ["8.8.8.8"],
    )
    policy.validate_url("https://api.example.com/v1/resource")
    with pytest.raises(SecurityPolicyError, match="HTTPS"):
        policy.validate_url("http://api.example.com/v1/resource")
    with pytest.raises(SecurityPolicyError, match="allowlisted"):
        policy.validate_url("https://other.example.com")


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1"],
)
def test_ssrf_private_metadata_and_ipv6_targets_are_blocked(address: str) -> None:
    policy = EgressPolicy(
        [EgressDestination("api.example.com", frozenset({443}))],
        resolver=lambda _host: [address],
    )
    with pytest.raises(SecurityPolicyError, match="non-public"):
        policy.validate_url("https://api.example.com")


def test_secret_broker_returns_only_declared_opaque_handles() -> None:
    broker = SecretBroker(
        lambda reference: TemporarySecretHandle(
            reference, "opaque-lease", 2_000_000_000
        )
    )
    handle = broker.issue(
        "secretref:providers/mail/key",
        declared_references={"secretref:providers/mail/key"},
    )
    assert handle.opaque_handle == "opaque-lease"
    with pytest.raises(SecurityPolicyError, match="not declared"):
        broker.issue(
            "secretref:other/key", declared_references={"secretref:providers/mail/key"}
        )
    with pytest.raises(SecurityPolicyError, match="raw"):
        broker.issue("plaintext-password", declared_references={"plaintext-password"})
