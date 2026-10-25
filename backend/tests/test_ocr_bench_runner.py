"""ACR-36 / A8-4 — the bench runner's retry, pacing and reporting logic.

Offline: the extractor is a stub, so nothing here touches the API or a key. What is under test
is the machinery that decides whether a failure is transient, how long to wait, and how the run is
reported — the parts that determine whether the recorded baseline means anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from scripts.ocr_bench import run_bench, scoring
from scripts.ocr_bench.ground_truth import BY_LAYOUT, CORPUS

MODEL = "claude-haiku-5-5"

_RATE_LIMIT_MESSAGE = (
    "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': "
    "'This request would exceed the rate limit for your organization'}}"
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
        "Connection error.",
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


def test_backoff_is_exponential():
    assert run_bench._retry_after(attempt=0) == 8.0
    assert run_bench._retry_after(attempt=1) == 16.0
    assert run_bench._retry_after(attempt=2) == 32.0


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

    score = run_bench.score_one(spec, path, MODEL, extractor, verbose=False)

    assert calls["n"] == 3
    assert score.error is None
    assert score.header_accuracy == 1.0
    assert no_sleep == [8.0, 16.0]


def test_score_one_gives_up_after_max_retries(tmp_path, no_sleep):
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    def extractor(payload, mime):
        raise _Boom("429 Too Many Requests")

    score = run_bench.score_one(spec, path, MODEL, extractor, max_retries=2, verbose=False)

    assert score.error is not None and "429" in score.error
    assert len(no_sleep) == 2


def test_score_one_does_not_retry_a_permanent_failure(tmp_path, no_sleep):
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    def extractor(payload, mime):
        raise _Boom("401 Unauthorized: invalid API key")

    score = run_bench.score_one(spec, path, MODEL, extractor, verbose=False)

    assert "401" in score.error
    assert no_sleep == []


def test_score_one_records_latency_on_success(tmp_path):
    spec = BY_LAYOUT["rotated"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    score = run_bench.score_one(
        spec, path, MODEL, lambda payload, mime: _extraction(spec), verbose=False
    )
    assert score.latency_ms is not None and score.latency_ms >= 0
    assert score.provider == MODEL


def test_score_one_passes_the_declared_mime_type(tmp_path):
    """The PDF layout must reach the model as application/pdf, not as an image."""
    spec = BY_LAYOUT["multipage"]
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4")
    seen = {}

    def extractor(payload, mime):
        seen["mime"] = mime
        return _extraction(spec)

    run_bench.score_one(spec, path, MODEL, extractor, verbose=False)
    assert seen["mime"] == "application/pdf"


# ---------------------------------------------------------------------------
# run() and reporting
# ---------------------------------------------------------------------------


def test_run_scores_every_document_and_records_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        run_bench, "_extractor", lambda model: (lambda payload, mime: _extraction(_spec(mime)))
    )

    def _spec(mime):
        # The stub cannot know which document it was handed, so echo a perfect extraction for
        # whichever spec matches the mime type it received.
        return next(s for s in CORPUS if s.mime_type == mime)

    payload = run_bench.run([MODEL], repeat=1, out_dir=tmp_path, verbose=False)

    meta = payload["run"]
    assert meta["corpus"]["documents"] == len(CORPUS)
    assert meta["models"] == [MODEL]
    assert meta["effort"] == settings.anthropic_effort
    assert meta["git_sha"]
    assert meta["scorer"]["item_match_threshold"] == scoring.ITEM_MATCH_THRESHOLD
    assert payload["results"][MODEL]["calls"] == len(CORPUS)


def test_run_keys_every_arm_by_its_model(tmp_path, monkeypatch):
    """A head-to-head reports each model under its own ID, so the table names what actually ran."""
    monkeypatch.setattr(run_bench, "_extractor", lambda model: (lambda payload, mime: {"items": []}))

    payload = run_bench.run(
        ["claude-haiku-5-5", "claude-sonnet-5-5"], repeat=1, out_dir=tmp_path, verbose=False
    )

    assert list(payload["results"]) == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert payload["run"]["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_extractor_binds_the_requested_model(monkeypatch):
    """Each arm must call Claude with its own model, not whatever settings name as primary."""
    from app.services import ocr_service

    seen = {}

    def fake_extract(payload, mime, model=None):
        seen["model"] = model
        return {"items": []}

    monkeypatch.setattr(ocr_service, "_extract_with_claude", fake_extract)

    run_bench._extractor("claude-sonnet-5-5")(b"x", "image/png")
    assert seen["model"] == "claude-sonnet-5-5"


def test_default_arms_are_the_configured_primary_and_fallback(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_model", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_fallback_model", "claude-sonnet-5-5")
    assert run_bench.configured_models() == ["claude-haiku-5-5", "claude-sonnet-5-5"]


@pytest.mark.parametrize("fallback", ["", "claude-haiku-5-5"])
def test_default_arms_skip_a_disabled_or_duplicate_fallback(monkeypatch, fallback):
    monkeypatch.setattr(settings, "anthropic_model", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_fallback_model", fallback)
    assert run_bench.configured_models() == ["claude-haiku-5-5"]


def test_run_paces_requests_when_delay_is_set(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(
        run_bench, "_extractor", lambda model: (lambda payload, mime: {"items": []})
    )
    run_bench.run([MODEL], repeat=1, out_dir=tmp_path, verbose=False, delay=13.0)
    # One pause between calls, none before the first.
    assert no_sleep == [13.0] * (len(CORPUS) - 1)


# ---------------------------------------------------------------------------
# Bounding the retries (A8 / RU-08): an exhausted quota must cost minutes, not hours
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clock(monkeypatch):
    """A clock that advances only when the code sleeps.

    `no_sleep` stubs `sleep` but leaves `perf_counter` real, so wall-clock time never moves and a
    wall-clock budget can never trip — every assertion below would pass vacuously. Tying the two
    together is what makes these tests capable of failing.
    """
    now = {"t": 0.0}
    monkeypatch.setattr(run_bench.time, "perf_counter", lambda: now["t"])
    monkeypatch.setattr(run_bench.time, "sleep", lambda s: now.__setitem__("t", now["t"] + s))
    return now


def test_doc_budget_refuses_a_retry_it_cannot_afford(tmp_path, fake_clock):
    """The budget is checked against the delay we are ABOUT to sleep, not the time already spent.

    Sleeping 16s only to discover we are over budget wastes exactly what the budget protects.
    """
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")
    calls = {"n": 0}

    def extractor(payload, mime):
        calls["n"] += 1
        raise _Boom(_RATE_LIMIT_MESSAGE)  # backoff 8s, then 16s

    score = run_bench.score_one(
        spec, path, MODEL, extractor, max_retries=4, doc_budget_s=20.0, verbose=False
    )

    # One retry fits (0 + 8 <= 20); the second does not (8 + 16 > 20), so it stops at 2 attempts
    # rather than burning all four.
    assert calls["n"] == 2
    assert fake_clock["t"] == 8.0
    assert "budget" in score.error


def test_budget_exhaustion_is_recorded_as_an_error_not_a_zero_score(tmp_path, fake_clock):
    """The whole point: a quota failure must not drag the accuracy average down.

    Scoring 429s as bad extractions is what made the first live run report 0.483 F1.
    """
    spec = BY_LAYOUT["gridded"]
    path = tmp_path / "doc.png"
    path.write_bytes(b"x")

    good = run_bench.score_one(
        spec, path, MODEL, lambda p, m: _extraction(spec), verbose=False
    )
    starved = run_bench.score_one(
        spec,
        path,
        MODEL,
        lambda p, m: (_ for _ in ()).throw(_Boom(_RATE_LIMIT_MESSAGE)),
        doc_budget_s=0.0,
        verbose=False,
    )

    corpus = scoring.score_corpus([good, starved])

    assert len(corpus.succeeded) == 1 and len(corpus.failed) == 1
    # Accuracy is identical with and without the starved document — it is excluded, not averaged in.
    assert corpus.header_accuracy == scoring.score_corpus([good]).header_accuracy


def test_arm_is_abandoned_after_consecutive_failures(tmp_path, monkeypatch, fake_clock):
    """Quota exhaustion is a GLOBAL condition — grinding through the corpus buys only wall time."""
    calls = {"n": 0}

    def always_429(payload, mime):
        calls["n"] += 1
        raise _Boom(_RATE_LIMIT_MESSAGE)

    monkeypatch.setattr(run_bench, "_extractor", lambda model: always_429)

    payload = run_bench.run(
        [MODEL],
        repeat=3,
        out_dir=tmp_path,
        verbose=False,
        doc_budget_s=0.0,
        quota_abort_after=3,
    )

    assert MODEL in payload["incomplete_arms"]
    assert calls["n"] == 3, "should stop at the breaker, not attempt all 7 x 3 documents"
    assert len(payload["results"][MODEL]["documents"]) == 3


def test_a_healthy_arm_reports_no_incomplete_arms(tmp_path, monkeypatch, no_sleep):
    """Negative control: the key is present-and-empty on a clean run, never absent.

    A reader must not have to infer completeness from a missing key.
    """
    monkeypatch.setattr(
        run_bench,
        "_extractor",
        lambda model: (lambda payload, mime: _extraction(BY_LAYOUT["gridded"])),
    )

    payload = run_bench.run([MODEL], repeat=1, out_dir=tmp_path, verbose=False)

    assert payload["incomplete_arms"] == {}
    assert payload["run"]["doc_budget_s"] == run_bench._DOC_BUDGET_S
    assert payload["run"]["quota_abort_after"] == run_bench._QUOTA_ABORT_AFTER


def test_an_intermittent_failure_does_not_trip_the_breaker(tmp_path, monkeypatch, fake_clock):
    """A success between failures resets the counter — the breaker fires on a run of them."""
    spec = BY_LAYOUT["gridded"]
    calls = {"n": 0}

    def flaky(payload, mime):
        calls["n"] += 1
        if calls["n"] % 2:  # fail, succeed, fail, succeed, ...
            raise _Boom(_RATE_LIMIT_MESSAGE)
        return _extraction(spec)

    monkeypatch.setattr(run_bench, "_extractor", lambda model: flaky)

    payload = run_bench.run(
        [MODEL], repeat=1, out_dir=tmp_path, verbose=False, doc_budget_s=0.0, quota_abort_after=3
    )

    assert payload["incomplete_arms"] == {}
    assert len(payload["results"][MODEL]["documents"]) == len(CORPUS)


def test_cli_exits_nonzero_when_an_arm_is_abandoned(tmp_path, monkeypatch, fake_clock):
    """A publication capture must not report success on a comparison with a missing side."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        run_bench,
        "_extractor",
        lambda model: (lambda payload, mime: (_ for _ in ()).throw(_Boom("429 rate limit"))),
    )

    code = run_bench.main(
        ["--model", MODEL, "--out", str(tmp_path), "--doc-budget", "0", "--quiet"]
    )

    assert code == 1
    # Artifacts are still written: an abandoned arm is when evidence matters most.
    payload = json.loads((tmp_path / "ocr-bench.json").read_text())
    assert MODEL in payload["incomplete_arms"]
    assert "Incomplete arms" in (tmp_path / "ocr-bench.md").read_text()


def test_markdown_report_separates_accuracy_from_availability():
    payload = {
        "run": {
            "captured_at": "2026-07-31T00:00:00+00:00",
            "git_sha": "abc1234",
            "host": "Darwin arm64",
            "python": "3.13.13",
            "models": [MODEL],
            "effort": "medium",
            "repeat": 1,
            "corpus": {"documents": 1, "layouts": ["gridded"], "line_items": 3},
            "scorer": {
                "item_match_threshold": 0.75,
                "text_field_threshold": 0.9,
                "quantity_tolerance": 0.01,
            },
        },
        "results": {
            MODEL: {
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
                    {"layout": "gridded", "error": "RateLimitError: Error code: 429", "items": {"f1": 0.0}},
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
    assert "**Effort:** `medium`" in report
    assert f"| `{MODEL}` | 1.000 |" in report


def test_markdown_truncates_giant_api_error_payloads():
    """A single API error body can run to hundreds of characters of JSON."""
    payload = {
        "run": {
            "captured_at": "x",
            "git_sha": "y",
            "host": "h",
            "python": "3.13",
            "models": [MODEL],
            "effort": "medium",
            "repeat": 1,
            "corpus": {"documents": 1, "layouts": ["gridded"], "line_items": 1},
            "scorer": {
                "item_match_threshold": 0.75,
                "text_field_threshold": 0.9,
                "quantity_tolerance": 0.01,
            },
        },
        "results": {
            MODEL: {
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
                    {"layout": "gridded", "error": "APIStatusError: " + "x" * 4000, "items": {"f1": 0.0}}
                ],
            }
        },
    }
    report = run_bench.format_markdown(payload)
    error_line = next(line for line in report.splitlines() if line.startswith(f"- `{MODEL}`"))
    assert len(error_line) < 220
    assert "| `gridded` | n/a |" in report


def test_cli_rejects_a_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run_bench.main(["--model", MODEL]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_cli_rejects_a_nonsense_repeat(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert run_bench.main(["--model", MODEL, "--repeat", "0"]) == 2
    assert "--repeat" in capsys.readouterr().err


def test_cli_writes_both_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        run_bench, "_extractor", lambda model: (lambda payload, mime: {"items": []})
    )

    assert run_bench.main(["--model", MODEL, "--out", str(tmp_path), "--quiet"]) == 0

    written = json.loads((tmp_path / "ocr-bench.json").read_text())
    assert written["run"]["models"] == [MODEL]
    assert (tmp_path / "ocr-bench.md").read_text().startswith("# OCR model comparison")


def test_cli_defaults_to_the_configured_models(tmp_path, monkeypatch):
    """No --model means bench exactly what production would run, primary and fallback."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(settings, "anthropic_model", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_fallback_model", "claude-sonnet-5-5")
    monkeypatch.setattr(
        run_bench, "_extractor", lambda model: (lambda payload, mime: {"items": []})
    )

    assert run_bench.main(["--out", str(tmp_path), "--quiet"]) == 0

    written = json.loads((tmp_path / "ocr-bench.json").read_text())
    assert written["run"]["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
