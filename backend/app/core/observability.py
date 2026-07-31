"""A8-3 — per-request timing and structured request logs.

The API had no request-level observability: `logging.basicConfig` with a plain format, and no way
to answer "how long did that take, which route was it, and which log lines belong to the same
request." This module supplies the whole **API** row of the A8 evidence table.

One line per request, on the `acra.request` logger:

    {"ts":"…","level":"INFO","logger":"acra.request","message":"POST /api/v1/deliveries 200 42.7ms",
     "request_id":"a3f9c1d20b74","method":"POST","route":"/api/v1/deliveries/{delivery_id}",
     "status":200,"duration_ms":42.7}

Two decisions worth knowing about:

* **The route template is logged, not the raw path.** `/api/v1/deliveries/{delivery_id}`, not
  `/api/v1/deliveries/8231`. Raw paths put every id in its own bucket and make the latency numbers
  unaggregatable — which is the entire point of collecting them.
* **Timing is in a `try/finally`.** A handler that raises is exactly the request you most want
  timed, so the log line is emitted before the exception continues on to the app's
  `Exception` handler.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_LOGGER = "acra.request"
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Attribute names LogRecord sets itself. Anything outside this set arrived via `extra=` and is
# part of the structured payload. Derived from a throwaway record so it tracks the running
# Python rather than a hand-maintained list that rots.
_RESERVED_RECORD_KEYS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", (), None))
) | {"message", "asctime", "taskName"}


class StructuredFormatter(logging.Formatter):
    """Render each record as a single JSON object, merging in any `extra=` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_format: str | None = None, level: int = logging.INFO) -> None:
    """Install the root handler. Idempotent — replaces handlers rather than appending.

    Falls back to the text format for any unrecognised value, so a typo in `LOG_FORMAT` degrades
    to readable logs instead of taking the process down.
    """
    chosen = (log_format or settings.log_format or "text").lower()
    handler = logging.StreamHandler()
    handler.setFormatter(
        StructuredFormatter() if chosen == "json" else logging.Formatter(TEXT_FORMAT)
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def route_label(request: Request) -> str:
    """The matched route template, falling back to the raw path when nothing matched (404)."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def request_id_headers(request: Request) -> dict[str, str]:
    """The `X-Request-ID` header for a response this middleware cannot reach.

    Starlette lifts an `Exception` handler out to `ServerErrorMiddleware`, which wraps *outside*
    every user middleware. So a genuinely unhandled exception is converted to a 500 above this
    middleware, and the response never passes back through `dispatch` to be tagged — the one case
    where a caller most needs an id to quote. The app's 500 handler calls this to close that gap.
    """
    request_id = getattr(request.state, "request_id", None)
    return {REQUEST_ID_HEADER: request_id} if request_id else {}


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Time every request, tag it with a correlatable id, and log one structured line."""

    def __init__(self, app: ASGIApp, logger_name: str = REQUEST_LOGGER) -> None:
        super().__init__(app)
        self.logger = logging.getLogger(logger_name)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        start = time.perf_counter()
        # If call_next raises, the request still ended in a 500 — record it as one.
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            route = route_label(request)
            self.logger.info(
                "%s %s %s %.1fms",
                request.method,
                route,
                status_code,
                duration_ms,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "route": route,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
