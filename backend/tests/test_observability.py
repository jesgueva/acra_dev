"""ACR-43 / A8-3 — request-timing middleware and structured logs.

Driven through a small local FastAPI app rather than `app.main`, so these assert the middleware's
behaviour without depending on the RBAC 3-query mock sequence.
"""
import json
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette import status

from app.core.observability import (
    REQUEST_ID_HEADER,
    REQUEST_LOGGER,
    RequestTimingMiddleware,
    StructuredFormatter,
    configure_logging,
)


@pytest.fixture
def client():
    """An app shaped like `app.main`: the timing middleware plus a catch-all 500 handler."""
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request, exc):  # pragma: no cover - mirrors app.main
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/items/{item_id}")
    async def item(item_id: int):
        return {"item_id": item_id}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/forbidden")
    async def forbidden():
        raise HTTPException(status_code=403, detail="nope")

    # raise_server_exceptions=False so the app's 500 handler runs instead of TestClient re-raising.
    return TestClient(app, raise_server_exceptions=False)


def _records(caplog):
    return [r for r in caplog.records if r.name == REQUEST_LOGGER]


# ---------------------------------------------------------------------------
# the happy path


def test_logs_one_line_per_request(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/ok")

    records = _records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.method == "GET"
    assert record.route == "/ok"
    assert record.status == 200
    assert record.duration_ms >= 0
    assert record.request_id


def test_logs_the_route_template_not_the_raw_path(client, caplog):
    """The whole reason the numbers aggregate: /items/{item_id}, never /items/42."""
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/items/42")

    record = _records(caplog)[0]
    assert record.route == "/items/{item_id}"
    assert "42" not in record.route


# ---------------------------------------------------------------------------
# request id correlation


def test_generates_and_echoes_a_request_id(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/ok")

    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed
    assert _records(caplog)[0].request_id == echoed, "log line must match the response header"


def test_reuses_a_supplied_request_id(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/ok", headers={REQUEST_ID_HEADER: "manual-trace-1"})

    assert response.headers[REQUEST_ID_HEADER] == "manual-trace-1"
    assert _records(caplog)[0].request_id == "manual-trace-1"


def test_request_ids_are_unique_per_request(client):
    ids = {client.get("/ok").headers[REQUEST_ID_HEADER] for _ in range(5)}
    assert len(ids) == 5


# ---------------------------------------------------------------------------
# error paths


def test_logs_a_404_with_the_raw_path(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/no-such-route")

    assert response.status_code == 404
    record = _records(caplog)[0]
    assert record.status == 404
    assert record.route == "/no-such-route", "no route matched, so fall back to the path"


def test_logs_an_http_exception_status(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/forbidden")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert _records(caplog)[0].status == 403


def test_a_raising_handler_is_still_logged_and_still_returns_500(client, caplog):
    """The try/finally regression test.

    A handler that blows up is the request you most want timed. The log line must be emitted AND
    the exception must continue on so the app's handler produces its 500 body.
    """
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}

    records = _records(caplog)
    assert len(records) == 1, "the failing request must still produce exactly one line"
    assert records[0].status == 500
    assert records[0].route == "/boom"
    assert records[0].duration_ms >= 0


# ---------------------------------------------------------------------------
# formatter + configuration


def test_structured_formatter_emits_parseable_json():
    record = logging.LogRecord(
        "acra.request", logging.INFO, __file__, 1, "GET /ok 200", (), None
    )
    record.request_id = "abc123"
    record.status = 200

    payload = json.loads(StructuredFormatter().format(record))
    assert payload["logger"] == "acra.request"
    assert payload["level"] == "INFO"
    assert payload["message"] == "GET /ok 200"
    assert payload["request_id"] == "abc123"
    assert payload["status"] == 200
    assert payload["ts"].endswith("+00:00")


def test_structured_formatter_includes_exception_text():
    try:
        raise ValueError("nope")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "acra", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    payload = json.loads(StructuredFormatter().format(record))
    assert "ValueError: nope" in payload["exc_info"]


def test_structured_formatter_survives_unserialisable_extras():
    record = logging.LogRecord("acra", logging.INFO, __file__, 1, "x", (), None)
    record.weird = object()
    assert json.loads(StructuredFormatter().format(record))["weird"].startswith("<object")


@pytest.mark.parametrize(
    "fmt,expected", [("json", StructuredFormatter), ("text", logging.Formatter)]
)
def test_configure_logging_selects_the_formatter(fmt, expected):
    configure_logging(fmt)
    handler = logging.getLogger().handlers[0]
    assert type(handler.formatter) is expected


def test_configure_logging_falls_back_to_text_on_a_bad_value():
    """A typo in LOG_FORMAT must degrade to readable logs, not crash the process."""
    configure_logging("jsn")
    assert type(logging.getLogger().handlers[0].formatter) is logging.Formatter


def test_configure_logging_is_idempotent():
    configure_logging("text")
    configure_logging("text")
    assert len(logging.getLogger().handlers) == 1


def test_json_logging_round_trips_a_real_request(client, capsys):
    """End to end: with JSON configured, the emitted line parses and carries the request fields."""
    configure_logging("json")
    try:
        client.get("/items/7", headers={REQUEST_ID_HEADER: "trace-json"})
        captured = capsys.readouterr().err
        line = next(
            line for line in captured.splitlines() if '"acra.request"' in line
        )
        payload = json.loads(line)
        assert payload["route"] == "/items/{item_id}"
        assert payload["status"] == 200
        assert payload["request_id"] == "trace-json"
        assert payload["method"] == "GET"
        assert payload["duration_ms"] >= 0
    finally:
        configure_logging("text")
