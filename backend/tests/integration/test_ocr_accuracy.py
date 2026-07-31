"""ACR-36 / A8-4 — the OCR no-regression gate.

`scripts/validation/ocr_roundtrip.py` ran one document and *printed* its comparison without ever
asserting or exiting non-zero, so no OCR regression could fail anything. This file is the asserted
replacement: measured accuracy must stay within tolerance of a recorded baseline.

Two halves, and the split is deliberate:

* **Offline** (always runs, no keys, no network) — the baseline file is well-formed, and the gate
  comparison itself is exercised in both directions. Without the negative control the gate could
  be a function that always returns "pass" and nothing would notice.
* **Live** (opt-in via `OCR_BENCH_LIVE=1` plus the provider's API key) — the real head-to-head
  against the corpus. Costs money and needs network, so CI never runs it.

Re-record the baseline with:

    cd backend && python -m scripts.ocr_bench.run_bench --provider both --repeat 3
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.ocr_bench import scoring
from scripts.ocr_bench.ground_truth import CORPUS

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "ocr" / "baseline.json"

LIVE = os.getenv("OCR_BENCH_LIVE") == "1"
ENV_KEYS = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


@pytest.fixture(scope="module")
def baseline() -> dict:
    if not BASELINE_PATH.exists():
        pytest.fail(f"baseline missing: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Offline — the baseline contract and the gate's own logic
# ---------------------------------------------------------------------------


def test_baseline_records_how_it_was_produced(baseline):
    """A number with no provenance cannot be defended in a writeup."""
    run = baseline["run"]
    assert run["git_sha"] and run["git_sha"] != "unknown"
    assert run["captured_at"] and run["host"] and run["python"]
    assert run["repeat"] >= 1
    assert run["corpus"]["documents"] == len(CORPUS)
    assert run["scorer"]["item_match_threshold"] == scoring.ITEM_MATCH_THRESHOLD
    assert run["scorer"]["quantity_tolerance"] == scoring.QUANTITY_TOLERANCE


def test_baseline_covers_both_providers(baseline):
    assert set(baseline["providers"]) == {"gemini", "claude"}
    for provider, metrics in baseline["providers"].items():
        assert baseline["run"]["models"][provider]
        for metric in scoring.GATE_METRICS:
            assert 0.0 <= metrics[metric] <= 1.0, f"{provider}.{metric} out of range"


@pytest.mark.parametrize("provider", ["gemini", "claude"])
def test_a_perfect_run_passes_the_gate(baseline, provider):
    perfect = {metric: 1.0 for metric in scoring.GATE_METRICS}
    assert scoring.compare_to_baseline(perfect, baseline["providers"][provider]) == []


@pytest.mark.parametrize("provider", ["gemini", "claude"])
def test_a_degraded_run_fails_the_gate(baseline, provider):
    """The negative control.

    Without this the gate could be vacuous — a comparison that always passes looks exactly like a
    model that never regresses. A run scoring zero everywhere must fail every enforced metric.
    """
    collapsed = {metric: 0.0 for metric in scoring.GATE_METRICS}
    failures = scoring.compare_to_baseline(collapsed, baseline["providers"][provider])
    assert {f.metric for f in failures} == set(scoring.GATE_METRICS)
    assert all("measured 0.0000" in str(f) for f in failures)


def test_gate_catches_a_drop_just_beyond_tolerance(baseline):
    """A regression one point past the tolerance band must fail, not squeak through."""
    metrics = baseline["providers"]["gemini"]
    just_over = {
        metric: metrics[metric] - scoring.DEFAULT_TOLERANCE - 0.01
        for metric in scoring.GATE_METRICS
    }
    assert len(scoring.compare_to_baseline(just_over, metrics)) == len(scoring.GATE_METRICS)


def test_gate_tolerates_a_drop_inside_the_band(baseline):
    """Model nondeterminism inside the tolerance is not a regression."""
    metrics = baseline["providers"]["gemini"]
    inside = {
        metric: max(0.0, metrics[metric] - scoring.DEFAULT_TOLERANCE + 0.01)
        for metric in scoring.GATE_METRICS
    }
    assert scoring.compare_to_baseline(inside, metrics) == []


def test_gate_ignores_metrics_absent_from_the_baseline():
    """A baseline recorded before a metric existed must not fail the run for that metric.

    Only metrics the baseline actually records are enforced, so adding a new metric to the scorer
    does not retroactively fail every run against an older baseline.
    """
    measured = {"header_accuracy": 1.0, "item_f1": 0.0}
    assert scoring.compare_to_baseline(measured, {"header_accuracy": 1.0}) == []


def test_gate_fails_when_a_baselined_metric_is_missing_from_the_run():
    """The converse, and the more dangerous direction.

    If the baseline enforces a metric the measured run does not report, that must fail rather than
    silently pass — otherwise dropping a metric from the bench would look like a green gate.
    """
    failures = scoring.compare_to_baseline({"item_f1": 1.0}, {"header_accuracy": 0.96})
    assert [f.metric for f in failures] == ["header_accuracy"]
    assert failures[0].measured == 0.0


# ---------------------------------------------------------------------------
# Live — the real providers against the real corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["gemini", "claude"])
def test_live_accuracy_meets_baseline(baseline, provider, tmp_path):
    if not LIVE:
        pytest.skip("live provider bench — set OCR_BENCH_LIVE=1 to run")
    if not os.getenv(ENV_KEYS[provider]):
        pytest.skip(f"{ENV_KEYS[provider]} not set")

    from scripts.ocr_bench import run_bench

    payload = run_bench.run([provider], repeat=1, out_dir=tmp_path, verbose=False)
    measured = payload["results"][provider]

    failures = scoring.compare_to_baseline(measured, baseline["providers"][provider])
    assert not failures, (
        f"{provider} regressed against the recorded baseline:\n  "
        + "\n  ".join(str(f) for f in failures)
    )
