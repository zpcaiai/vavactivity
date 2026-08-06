"""Low-cardinality Prometheus metrics for the API process."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

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


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            registry.observe(request.method, route, status, time.perf_counter() - started)
