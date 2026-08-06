from pathlib import Path

import pytest

from vav.core.secrets import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    MountedFileSecretProvider,
    SecretValue,
)


@pytest.mark.asyncio
async def test_secret_values_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATCH19_SECRET", "sensitive-value")
    value = await EnvironmentSecretProvider().get_secret("env://BATCH19_SECRET")
    assert value.value == "sensitive-value"
    assert "sensitive-value" not in repr(value)
    assert str(value) == "********"


@pytest.mark.asyncio
async def test_mounted_provider_rejects_path_escape(tmp_path: Path) -> None:
    provider = MountedFileSecretProvider(tmp_path)
    with pytest.raises(ValueError, match="escape"):
        await provider.get_secret("docker://../outside")


@pytest.mark.asyncio
async def test_composite_routes_only_registered_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATCH19_SECRET", "safe")
    provider = CompositeSecretProvider({"env": EnvironmentSecretProvider()})
    assert await provider.get_secret("env://BATCH19_SECRET") == SecretValue("safe")
    with pytest.raises(ValueError, match="not configured"):
        await provider.get_secret("cloud://production/secret")
