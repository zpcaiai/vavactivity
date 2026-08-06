"""Low-cardinality Prometheus metrics for the API process."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from threading import Lock

from starlette.types import ASGIApp, Message, Receive, Scope, Send

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._durations: defaultdict[tuple[str, str], float] = defaultdict(float)
        self._buckets: Counter[tuple[str, str, float]] = Counter()

    def observe(self, method: str, route: str, status: int, duration: float) -> None:
        with self._lock:
            self._requests[(method, route, status)] += 1
            self._durations[(method, route)] += duration
            for bucket in BUCKETS:
                if duration <= bucket:
                    self._buckets[(method, route, bucket)] += 1

    def render(self) -> str:
        lines = [
            "# HELP http_requests_total Total HTTP requests.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            requests = self._requests.copy()
            durations = dict(self._durations)
            buckets = self._buckets.copy()
        for (method, route, status), count in sorted(requests.items()):
            labels = f'method="{method}",route="{route}",status="{status}"'
            lines.append(f"http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP http_request_duration_seconds HTTP request latency.",
                "# TYPE http_request_duration_seconds histogram",
            ]
        )
        for method, route in sorted(durations):
            base = f'method="{method}",route="{route}"'
            total = sum(
                count
                for (request_method, request_route, _), count in requests.items()
                if request_method == method and request_route == route
            )
            for bucket in BUCKETS:
                count = buckets[(method, route, bucket)]
                lines.append(
                    f'http_request_duration_seconds_bucket{{{base},le="{bucket}"}} {count}'
                )
            lines.append(f'http_request_duration_seconds_bucket{{{base},le="+Inf"}} {total}')
            lines.append(
                f"http_request_duration_seconds_sum{{{base}}} {durations[(method, route)]}"
            )
            lines.append(f"http_request_duration_seconds_count{{{base}}} {total}")
        return "\n".join(lines) + "\n"


registry = MetricsRegistry()


class MetricsMiddleware:
    """Record route templates from the shared ASGI scope.

    A pure ASGI middleware observes the same scope that FastAPI's router
    updates. This remains compatible with Starlette 1.4's isolated
    ``BaseHTTPMiddleware`` request scopes and prevents metrics from ever
    falling back to a raw path containing user identifiers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            fastapi_scope = scope.get("fastapi")
            effective_context = (
                fastapi_scope.get("effective_route_context")
                if isinstance(fastapi_scope, dict)
                else None
            )
            route_object = scope.get("route")
            # FastAPI 0.141 keeps the fully-prefixed template on its effective
            # route context while the Starlette route contains only the leaf.
            route = str(
                getattr(
                    effective_context,
                    "path",
                    getattr(route_object, "path", "unmatched"),
                )
            )
            registry.observe(str(scope["method"]), route, status, time.perf_counter() - started)
