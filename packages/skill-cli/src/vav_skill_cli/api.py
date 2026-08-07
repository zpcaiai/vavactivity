"""Minimal authenticated Skill control-plane client."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SkillApiError(RuntimeError):
    pass


class SkillApiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        configured_url = base_url or os.getenv("VAV_API_URL") or "http://localhost:8000/api/v1"
        self.base_url = configured_url.rstrip("/")
        self.token = token or os.getenv("VAV_ACCESS_TOKEN")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - caller controls configured API
                parsed = json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise SkillApiError(f"Skill API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise SkillApiError(f"Skill API is unavailable: {exc.reason}") from exc
        return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
