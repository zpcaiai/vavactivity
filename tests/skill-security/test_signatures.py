from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vav_skill_runtime.security import SecurityPolicyError, SignatureVerifier


def _fixture() -> tuple[bytes, bytes, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = b"deterministic-vavskill-package"
    return public, payload, private.sign(payload)


def test_verified_signature_accepts_exact_package() -> None:
    public, payload, signature = _fixture()
    verifier = SignatureVerifier({"publisher-key": public})
    verifier.verify(
        key_id="publisher-key",
        payload=payload,
        signature=signature,
        checksum=hashlib.sha256(payload).hexdigest(),
    )


def test_tampering_unknown_and_revoked_keys_are_rejected() -> None:
    public, payload, signature = _fixture()
    verifier = SignatureVerifier({"publisher-key": public})
    with pytest.raises(SecurityPolicyError, match="checksum"):
        verifier.verify(
            key_id="publisher-key",
            payload=payload + b"tampered",
            signature=signature,
            checksum=hashlib.sha256(payload).hexdigest(),
        )
    with pytest.raises(SecurityPolicyError, match="trusted"):
        verifier.verify(
            key_id="unknown",
            payload=payload,
            signature=signature,
            checksum=hashlib.sha256(payload).hexdigest(),
        )
    revoked = SignatureVerifier(
        {"publisher-key": public}, revoked_keys={"publisher-key"}
    )
    with pytest.raises(SecurityPolicyError, match="revoked"):
        revoked.verify(
            key_id="publisher-key",
            payload=payload,
            signature=signature,
            checksum=hashlib.sha256(payload).hexdigest(),
        )
