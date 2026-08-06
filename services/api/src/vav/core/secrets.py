"""Secret-provider boundaries with redacted values and strict reference routing."""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


@dataclass(frozen=True, repr=False)
class SecretValue:
    value: str
    version: str | None = None

    def __repr__(self) -> str:
        return f"SecretValue(value='********', version={self.version!r})"

    def __str__(self) -> str:
        return "********"


class SecretProvider(Protocol):
    async def get_secret(self, reference: str) -> SecretValue: ...


class EnvironmentSecretProvider:
    async def get_secret(self, reference: str) -> SecretValue:
        name = reference.removeprefix("env://")
        if not name or not name.replace("_", "").isalnum() or name.upper() != name:
            raise ValueError("invalid environment secret reference")
        value = os.environ.get(name)
        if value is None:
            raise KeyError(f"secret reference is unavailable: env://{name}")
        return SecretValue(value=value)


class MountedFileSecretProvider:
    def __init__(self, root: Path, schemes: tuple[str, ...] = ("file", "docker", "k8s")) -> None:
        self.root = root.resolve()
        self.schemes = schemes

    async def get_secret(self, reference: str) -> SecretValue:
        scheme, separator, name = reference.partition("://")
        if not separator or scheme not in self.schemes:
            raise ValueError("unsupported mounted-secret reference")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("secret references cannot escape their mounted root")
        path = (self.root / Path(*pure.parts)).resolve()
        if self.root not in path.parents:
            raise ValueError("secret references cannot escape their mounted root")
        value = path.read_text(encoding="utf-8").rstrip("\n")
        if not value:
            raise ValueError("secret value is empty")
        return SecretValue(value=value)


class CloudSecretManagerProvider:
    def __init__(self, resolver: Callable[[str], Awaitable[SecretValue]]) -> None:
        self.resolver = resolver

    async def get_secret(self, reference: str) -> SecretValue:
        name = reference.removeprefix("cloud://")
        if not name or name == reference:
            raise ValueError("invalid cloud secret reference")
        return await self.resolver(name)


class SopsBoundaryProvider:
    """Read an already-decrypted, access-controlled SOPS JSON mount.

    This process never decrypts source-controlled ciphertext or invokes a shell. The deployment
    boundary is responsible for materializing the decrypted file in a restricted temporary mount.
    """

    def __init__(self, decrypted_file: Path) -> None:
        self.decrypted_file = decrypted_file

    async def get_secret(self, reference: str) -> SecretValue:
        name = reference.removeprefix("sops://")
        if not name or name == reference:
            raise ValueError("invalid SOPS secret reference")
        values = json.loads(self.decrypted_file.read_text(encoding="utf-8"))
        if not isinstance(values, dict) or not isinstance(values.get(name), str):
            raise KeyError(f"secret reference is unavailable: {reference}")
        return SecretValue(value=values[name])


class CompositeSecretProvider:
    def __init__(self, providers: dict[str, SecretProvider]) -> None:
        self.providers = providers

    async def get_secret(self, reference: str) -> SecretValue:
        scheme = reference.partition("://")[0]
        provider = self.providers.get(scheme)
        if provider is None:
            raise ValueError(f"secret scheme is not configured: {scheme}")
        return await provider.get_secret(reference)
