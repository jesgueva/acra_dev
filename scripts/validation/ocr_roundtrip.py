"""ACRA MES — real OCR round-trip against the live endpoint.

Renders the labelled synthetic BOL corpus, uploads every document to the running
`POST /api/v1/deliveries/ocr`, scores each extraction against ground truth, and **exits non-zero
if accuracy falls below the recorded baseline**. This exercises the REAL external integration end
to end — not a mock.

Two things changed here in ACR-36, both of which had made this script unable to fail:

1. It ran one document and *printed* a comparison. No assertion, no `sys.exit(1)` — an OCR
   regression could not break anything, including this script.
2. It aligned line items positionally (`got_items[gi]`), so one dropped or reordered row misscored
   every row after it.

Both now come from `backend/scripts/ocr_bench/scoring.py`, shared with the provider bench and the
pytest gate — one scorer, three callers.

Usage (from backend/, with the API on :8000):

    PYTHONPATH=backend python ../scripts/validation/ocr_roundtrip.py [OUTPUT_DIR]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from scripts.ocr_bench import corpus, scoring
from scripts.ocr_bench.ground_truth import CORPUS

BASE = "http://localhost:8000"
DEFAULT_OUT = "/tmp/acra-ocr-roundtrip"

BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "ocr" / "baseline.json"
)

_MIME_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf"}


def _login(client: httpx.Client) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    rendered = corpus.render_all(out_dir)

    client = httpx.Client(base_url=BASE, timeout=120.0)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    print("REQUEST")
    print(f"  POST {BASE}/api/v1/deliveries/ocr   x{len(CORPUS)} documents")
    print("  auth: Bearer <admin JWT, redacted>")
    print(f"  corpus: {', '.join(spec.layout for spec in CORPUS)}")
    print()

    scores = []
    for spec in CORPUS:
        payload = rendered[spec.layout].read_bytes()
        filename = f"bol_{spec.layout}{_MIME_SUFFIX[spec.mime_type]}"

        response = client.post(
            "/api/v1/deliveries/ocr",
            headers=headers,
            files={"file": (filename, payload, spec.mime_type)},
        )
        if response.status_code != 200:
            scores.append(
                scoring.score_document(
                    spec, None, error=f"HTTP {response.status_code}: {response.text[:200]}"
                )
            )
            continue

        body = response.json()
        scores.append(scoring.score_document(spec, body, provider=body.get("provider")))

    print("FIELD-LEVEL ACCURACY (extracted vs. ground truth)")
    for score in scores:
        print(scoring.format_document_report(score))
        print()

    result = scoring.score_corpus(scores)
    print("SUMMARY")
    print(f"  header accuracy : {result.header_accuracy:.4f}")
    print(
        f"  line items      : P={result.precision:.4f} R={result.recall:.4f}"
        f" F1={result.item_f1:.4f}"
    )
    print(f"  numeric accuracy: {result.numeric_accuracy:.4f}")

    if not BASELINE_PATH.exists():
        print(f"\nFAIL — baseline not found at {BASELINE_PATH}")
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # The endpoint runs the production fallback chain, so the answering provider varies per
    # document. Gate against the weaker of the two recorded baselines — it is the only floor the
    # chain as a whole can be held to.
    floor = {
        metric: min(p[metric] for p in baseline["providers"].values())
        for metric in scoring.GATE_METRICS
    }
    failures = scoring.compare_to_baseline(result, floor)

    print()
    print(
        "  gate floor      : "
        + ", ".join(
            f"{name}>={value - scoring.DEFAULT_TOLERANCE:.4f}" for name, value in floor.items()
        )
    )
    if failures:
        print("\nFAIL — accuracy regressed against the recorded baseline:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print("\nOCR ACCURACY GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
