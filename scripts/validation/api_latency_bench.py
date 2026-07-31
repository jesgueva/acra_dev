"""ACRA MES — API latency benchmark (A8-2).

Drives a set of read endpoints over real HTTP against the running backend and writes a
provenance-stamped artifact pair via `app.core.benchmark`. This is the harness's first consumer;
A8-5 (comparative concurrency) and A8-6 (aggregation at volume) call the same library rather than
re-deriving percentile math.

Usage (backend must already be up on :8000):
    PYTHONPATH=backend python scripts/validation/api_latency_bench.py [OUT_DIR] [--requests N]

Exit code 0 unless authentication or an endpoint fails outright. It reports latency; it does not
assert a budget — the budget gate lives in the integration suite (RSK-04), and a benchmark that
fails the build on a noisy laptop is a benchmark people stop running.
"""
import argparse
import sys
from pathlib import Path

import httpx

from app.core.benchmark import BenchmarkRun

BASE = "http://localhost:8000"
WARMUP = 5

# (label, method, path) — read-only endpoints, so the benchmark is repeatable against one seed.
ENDPOINTS = [
    ("health", "GET", "/health"),
    ("inventory-list", "GET", "/api/v1/inventory/lots?limit=50"),
    ("products-list", "GET", "/api/v1/products"),
    ("deliveries-list", "GET", "/api/v1/deliveries"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="ACRA MES API latency benchmark")
    parser.add_argument("out_dir", nargs="?", default="validation-evidence")
    parser.add_argument("--requests", type=int, default=100, help="samples per endpoint")
    args = parser.parse_args()

    client = httpx.Client(base_url=BASE, timeout=30.0)

    print(f"== Authenticating against {BASE} ==")
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    if login.status_code != 200:
        print(f"  [FAIL] login -> {login.status_code}", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    print("  [PASS] login -> 200")

    written: list[Path] = []
    failed = False

    for label, method, path in ENDPOINTS:
        print(f"\n== {label}  ({method} {path}) ==")

        probe = client.request(method, path, headers=headers)
        if probe.status_code != 200:
            print(f"  [FAIL] {path} -> {probe.status_code}", file=sys.stderr)
            failed = True
            continue

        # Warm-up samples are discarded: the first request pays connection setup and any
        # lazy import, and folding that into p50 would misreport steady-state latency.
        for _ in range(WARMUP):
            client.request(method, path, headers=headers)

        run = BenchmarkRun(
            f"api-latency-{label}",
            endpoint=path,
            method=method,
            requests=args.requests,
            warmup=WARMUP,
        )
        for _ in range(args.requests):
            with run.time():
                client.request(method, path, headers=headers)

        stats = run.stats
        print(
            f"  n={stats['n']}  p50={stats['p50_ms']:.1f}ms  "
            f"p95={stats['p95_ms']:.1f}ms  p99={stats['p99_ms']:.1f}ms"
        )
        json_path, txt_path = run.write(args.out_dir)
        written += [json_path, txt_path]

    client.close()

    print(f"\n== Artifacts ({len(written)}) ==")
    for path in written:
        print(f"  {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
