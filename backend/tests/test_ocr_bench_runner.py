"""ACR-36 / A8-4 — the bench runner's retry, pacing and reporting logic.

Offline: the extractor is a stub, so nothing here touches a provider or a key. What is under test
is the machinery that decides whether a failure is transient, how long to wait, and how the run is
reported — the parts that determine whether the recorded baseline means anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ocr_bench import run_bench, scoring
from scripts.ocr_bench.ground_truth import BY_LAYOUT, CORPUS

_RATE_LIMIT_MESSAGE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current "
    "quota', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '21s'}]}}"
)


class _Boom(Exception):
    pass


# ---------------------------------------------------------------------------
# Which failures are worth retrying
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        _RATE_LIMIT_MESSAGE,
        "429 Too Many Requests",
        "Error code: 529 - overloaded_error",
        "503 Service Unavailable",
        "Read timeout",
    ],
)
def test_transient_failures_are_retryable(message):
    assert run_bench._is_retryable(_Boom(message))


@pytest.mark.parametrize(
    "message",
    [
        "401 Unauthorized: invalid API key",
        "400 Bad Request: unsupported mime type",
        "JSONDecodeError: Expecting value",
    ],
)
def test_permanent_failures_are_not_retryable(message):
    """Retrying a bad key or a malformed request just burns wall-clock time."""
    assert not run_bench._is_retryable(_Boom(message))


def test_provider_supplied_retry_delay_is_honoured():
    """Gemini tells us how long to wait; guessing would either thrash or over-sleep."""
    assert run_bench._retry_after(_Boom(_RATE_LIMIT_MESSAGE), attempt=0) == 22.0


def test_backoff_is_exponential_when_no_delay_is_supplied():
    exc = _Boom("429 Too Many Requests")
    assert run_bench._retry_after(exc, attempt=0) == 8.0
    assert run_bench._retry_after(exc, attempt=1) == 16.0
    assert run_bench._retry_after(exc, attempt=2) == 32.0


# ---------------------------------------------------------------------------
# score_one
# ---------------------------------------------------------------------------


def _extraction(spec):
    return {
        "supplier": spec.supplier,
        "carrier": spec.carrier,
        "bol_reference": spec.bol_reference,
        "delivery_date": spec.delivery_date.isoformat(),
        "items": [
            {
                "item_name": i.item_name,
                "quantity": i.quantity,
                "pallets": i.pallets,
                "units_per_pallet": i.units_per_pallet,
            }
            for i in spec.items
        ],
    }


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(run_bench.time, "sleep", slept.append)
    return slept


def test_score_one_retries_then_succeeds(tmp_path, no_sleep):
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"not really a png")
    calls = {"n": 0}

    def extractor(payload, mime):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom(_RATE_LIMIT_MESSAGE)
        return _extraction(spec)

    score = run_bench.score_one(spec, path, "gemini", extractor, verbose=False)

    assert calls["n"] == 3
    assert score.error is None
    assert score.header_accuracy == 1.0
    assert no_sleep == [22.0, 22.0]


def test_score_one_gives_up_after_max_retries(tmp_path, no_sleep):
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    def extractor(payload, mime):
        raise _Boom("429 Too Many Requests")

    score = run_bench.score_one(spec, path, "gemini", extractor, max_retries=2, verbose=False)

    assert score.error is not None and "429" in score.error
    assert len(no_sleep) == 2


def test_score_one_does_not_retry_a_permanent_failure(tmp_path, no_sleep):
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    def extractor(payload, mime):
        raise _Boom("401 Unauthorized: invalid API key")

    score = run_bench.score_one(spec, path, "claude", extractor, verbose=False)

    assert "401" in score.error
    assert no_sleep == []


def test_score_one_records_latency_on_success(tmp_path):
    spec = BY_LAYOUT["rotated"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    score = run_bench.score_one(
        spec, path, "gemini", lambda payload, mime: _extraction(spec), verbose=False
    )
    assert score.latency_ms is not None and score.latency_ms >= 0
    assert score.provider == "gemini"


def test_score_one_passes_the_declared_mime_type(tmp_path):
    """The PDF layout must reach the provider as application/pdf, not as an image."""
    spec = BY_LAYOUT["multipage"]
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4")
    seen = {}

    def extractor(payload, mime):
        seen["mime"] = mime
        return _extraction(spec)

    run_bench.score_one(spec, path, "claude", extractor, verbose=False)
    assert seen["mime"] == "application/pdf"


# ---------------------------------------------------------------------------
# run() and reporting
# ---------------------------------------------------------------------------


def test_run_scores_every_document_and_records_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        run_bench, "_extractor", lambda provider: (lambda payload, mime: _extraction(_spec(mime)))
    )

    def _spec(mime):
        # The stub cannot know which document it was handed, so echo a perfect extraction for
        # whichever spec matches the mime type it received.
        return next(s for s in CORPUS if s.mime_type == mime)

    payload = run_bench.run(["gemini"], repeat=1, out_dir=tmp_path, verbose=False)

    meta = payload["run"]
    assert meta["corpus"]["documents"] == len(CORPUS)
    assert meta["models"]["gemini"] == "gemini-2.5-flash"
    assert meta["git_sha"]
    assert meta["scorer"]["item_match_threshold"] == scoring.ITEM_MATCH_THRESHOLD
    assert payload["results"]["gemini"]["calls"] == len(CORPUS)


def test_run_paces_requests_when_delay_is_set(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(
        run_bench, "_extractor", lambda provider: (lambda payload, mime: {"items": []})
    )
    run_bench.run(["gemini"], repeat=1, out_dir=tmp_path, verbose=False, delay=13.0)
    # One pause between calls, none before the first.
    assert no_sleep == [13.0] * (len(CORPUS) - 1)


def test_markdown_report_separates_accuracy_from_availability():
    payload = {
        "run": {
            "captured_at": "2026-07-31T00:00:00+00:00",
            "git_sha": "abc1234",
            "host": "Darwin arm64",
            "python": "3.13.13",
            "models": {"gemini": "gemini-2.5-flash"},
            "repeat": 1,
            "corpus": {"documents": 1, "layouts": ["gridded"], "line_items": 3},
            "scorer": {
                "item_match_threshold": 0.75,
                "text_field_threshold": 0.9,
                "quantity_tolerance": 0.01,
            },
        },
        "results": {
            "gemini": {
                "header_accuracy": 1.0,
                "item_precision": 1.0,
                "item_recall": 1.0,
                "item_f1": 1.0,
                "numeric_accuracy": 1.0,
                "calls": 2,
                "scored": 1,
                "errors": 1,
                "error_rate": 0.5,
                "latency_ms": {"p50": 5000, "p95": 5000, "p99": 5000},
                "documents": [
                    {"layout": "gridded", "error": None, "items": {"f1": 1.0}},
                    {"layout": "gridded", "error": "ClientError: 429 RESOURCE_EXHAUSTED", "items": {"f1": 0.0}},
                ],
            }
        },
    }
    report = run_bench.format_markdown(payload)

    assert "## Accuracy" in report
    assert "## Availability and latency" in report
    assert "upper bound" in report
    # The failed call must not pull the per-layout F1 down to 0.5.
    assert "| `gridded` | 1.000 |" in report
    assert "## Errors" in report


def test_markdown_truncates_giant_provider_error_payloads():
    """A single Gemini 429 body runs to hundreds of characters of JSON."""
    payload = {
        "run": {
            "captured_at": "x",
            "git_sha": "y",
            "host": "h",
            "python": "3.13",
            "models": {"gemini": "gemini-2.5-flash"},
            "repeat": 1,
            "corpus": {"documents": 1, "layouts": ["gridded"], "line_items": 1},
            "scorer": {
                "item_match_threshold": 0.75,
                "text_field_threshold": 0.9,
                "quantity_tolerance": 0.01,
            },
        },
        "results": {
            "gemini": {
                "header_accuracy": 0.0,
                "item_precision": 0.0,
                "item_recall": 0.0,
                "item_f1": 0.0,
                "numeric_accuracy": 0.0,
                "calls": 1,
                "scored": 0,
                "errors": 1,
                "error_rate": 1.0,
                "latency_ms": {"p50": None, "p95": None, "p99": None},
                "documents": [
                    {"layout": "gridded", "error": "ClientError: " + "x" * 4000, "items": {"f1": 0.0}}
                ],
            }
        },
    }
    report = run_bench.format_markdown(payload)
    error_line = next(line for line in report.splitlines() if line.startswith("- `gemini`"))
    assert len(error_line) < 220
    assert "| `gridded` | n/a |" in report


def test_cli_rejects_a_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert run_bench.main(["--provider", "gemini"]) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_cli_rejects_a_nonsense_repeat(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert run_bench.main(["--provider", "gemini", "--repeat", "0"]) == 2
    assert "--repeat" in capsys.readouterr().err


def test_cli_writes_both_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        run_bench, "_extractor", lambda provider: (lambda payload, mime: {"items": []})
    )

    assert run_bench.main(["--provider", "gemini", "--out", str(tmp_path), "--quiet"]) == 0

    written = json.loads((tmp_path / "ocr-bench.json").read_text())
    assert written["run"]["models"] == {"gemini": "gemini-2.5-flash"}
    assert (tmp_path / "ocr-bench.md").read_text().startswith("# OCR provider comparison")
