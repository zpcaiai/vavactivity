"""HTTP transport for the map-provider adapters (MAP-001).

This is the only place in the discovery module that knows about HTTP. The
adapters call an injected async callable, so the domain and service layers stay
importable — and testable — with no network stack at all.

The transport deliberately does very little: one request, a bounded timeout,
and a translation of every failure mode into ``MapProviderUnavailable``. The
service layer already treats that as "keep the operator's typed address", which
is what MAP-001 requires, so a provider outage degrades instead of erroring.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import structlog

from vav.core.config import get_settings
from vav.modules.discovery.service import (
    MapProviderUnavailable,
    register_geocode_fetcher,
)

logger = structlog.get_logger(__name__)

#: Geocoding sits in the middle of an operator saving a venue. A long timeout
#: would hold the request open; failing fast and keeping the typed address is a
#: better trade than making the operator wait.
DEFAULT_TIMEOUT_SECONDS = 8.0


async def fetch_geocode_json(
    provider_code: str, url: str, params: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Perform one geocoding request and return the decoded payload.

    Never raises anything except :class:`MapProviderUnavailable`, so the caller
    has exactly one failure mode to handle.
    """

    timeout = get_settings().map_geocode_timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=dict(params))
    except httpx.HTTPError as exc:
        # Log the provider and the failure class, never the params: they carry
        # the API key and the member-visible address.
        logger.warning("geocode.transport_failed", provider=provider_code, error=type(exc).__name__)
        raise MapProviderUnavailable(f"{provider_code} transport error") from exc

    if response.status_code >= 400:
        logger.warning(
            "geocode.provider_error", provider=provider_code, status=response.status_code
        )
        raise MapProviderUnavailable(f"{provider_code} returned {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise MapProviderUnavailable(f"{provider_code} returned a non-JSON body") from exc

    if not isinstance(payload, dict):
        raise MapProviderUnavailable(f"{provider_code} returned an unexpected payload shape")
    return payload


def install_geocode_transport() -> None:
    """Wire the transport. Called once from the application lifespan.

    Registering unconditionally is safe: the adapters are only constructed when
    a provider flag is on and a key is configured, so an unconfigured
    deployment still never makes an outbound call.
    """

    register_geocode_fetcher(fetch_geocode_json)


def uninstall_geocode_transport() -> None:
    """Drop the transport, restoring the import-time (offline) behaviour."""

    register_geocode_fetcher(None)
