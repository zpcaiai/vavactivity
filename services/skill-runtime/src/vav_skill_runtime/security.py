"""Package signatures, egress controls, and scoped secret handles."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SecurityPolicyError(ValueError):
    pass


class SignatureVerifier:
    def __init__(self, trust_roots: dict[str, bytes], *, revoked_keys: Iterable[str] = ()) -> None:
        self._trust_roots = dict(trust_roots)
        self._revoked_keys = set(revoked_keys)

    def verify(self, *, key_id: str, payload: bytes, signature: bytes, checksum: str) -> None:
        if key_id in self._revoked_keys:
            raise SecurityPolicyError("signing key is revoked")
        encoded = self._trust_roots.get(key_id)
        if encoded is None:
            raise SecurityPolicyError("signing key is not trusted")
        actual_checksum = hashlib.sha256(payload).hexdigest()
        if actual_checksum != checksum:
            raise SecurityPolicyError("package checksum mismatch")
        try:
            Ed25519PublicKey.from_public_bytes(encoded).verify(signature, payload)
        except (InvalidSignature, ValueError) as exc:
            raise SecurityPolicyError("package signature is invalid") from exc


@dataclass(frozen=True)
class EgressDestination:
    host: str
    ports: frozenset[int]


Resolver = Callable[[str], Iterable[str]]


def _system_resolver(host: str) -> Iterable[str]:
    return {str(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}


class EgressPolicy:
    def __init__(
        self,
        destinations: Iterable[EgressDestination],
        *,
        resolver: Resolver = _system_resolver,
    ) -> None:
        self._destinations = {item.host.rstrip(".").lower(): item for item in destinations}
        self._resolver = resolver

    @staticmethod
    def _public_address(value: str) -> bool:
        address = ipaddress.ip_address(value)
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SecurityPolicyError("egress requires credential-free HTTPS URLs")
        host = parsed.hostname.rstrip(".").lower()
        destination = self._destinations.get(host)
        if destination is None:
            raise SecurityPolicyError("egress host is not allowlisted")
        port = parsed.port or 443
        if port not in destination.ports:
            raise SecurityPolicyError("egress port is not allowlisted")
        try:
            addresses = tuple(self._resolver(host))
        except OSError as exc:
            raise SecurityPolicyError("egress DNS resolution failed") from exc
        if not addresses or not all(self._public_address(address) for address in addresses):
            raise SecurityPolicyError("egress resolves to a non-public address")


@dataclass(frozen=True)
class TemporarySecretHandle:
    reference: str
    opaque_handle: str
    expires_at_epoch: int


class SecretBroker:
    def __init__(self, issuer: Callable[[str], TemporarySecretHandle]) -> None:
        self._issuer = issuer

    def issue(self, reference: str, *, declared_references: Iterable[str]) -> TemporarySecretHandle:
        if reference not in frozenset(declared_references):
            raise SecurityPolicyError("secret reference was not declared by the Skill")
        if not reference.startswith("secretref:"):
            raise SecurityPolicyError("raw secret values are forbidden")
        return self._issuer(reference)
