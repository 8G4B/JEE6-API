import time

from fastapi import Request, Response
from prometheus_client import Counter, Histogram, make_asgi_app


REQUEST_COUNT = Counter(
    "jee6_api_http_requests_total",
    "Total number of HTTP requests handled by the API gateway.",
    ("method", "route", "status"),
)
REQUEST_DURATION = Histogram(
    "jee6_api_http_request_duration_seconds",
    "API gateway request duration in seconds.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

metrics_app = make_asgi_app()


async def observe_request(request: Request, call_next) -> Response:
    started_at = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration = time.perf_counter() - started_at
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        REQUEST_COUNT.labels(request.method, route_path, str(status)).inc()
        REQUEST_DURATION.labels(request.method, route_path).observe(duration)
