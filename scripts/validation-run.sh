#!/usr/bin/env bash
# validation-run.sh — reproducible evidence capture for the Early Implementation
# Validation Package (Hard Stop 3).
#
# From a clean-seeded database it runs the full validation pass and writes every
# artifact, each with a self-describing provenance header, into an output directory:
#
#   environment.txt              tool/runtime version snapshot
#   api-routes.txt               FastAPI route inventory (app.routes)
#   smoke-test-output.log        end-to-end smoke test (7 stages)
#   backend-suite-coverage.log   full pytest suite + coverage (CI 85% floor)
#   data-pipeline-validation.log receiving -> inventory integrity trace (real HTTP)
#   ocr-roundtrip.txt            real vision-LLM BOL extraction, gated against the
#                                recorded baseline (skipped w/o API key)
#   ocr-corpus/                  the labelled synthetic BOL corpus that was uploaded
#   api-latency-*.json/.txt      per-endpoint p50/p95/p99 latency (A8-2 benchmark harness)
#   concurrency-*.json/.txt      three-arm stock-drawdown ablation (A8-5 comparative study)
#   ocr-bench/ocr-bench.json     gemini vs claude head-to-head, machine-readable (A8-4)
#   ocr-bench/ocr-bench.md       the same comparison as a table for the writeup
#
# Usage (from repo root):
#   ./scripts/validation-run.sh [OUTPUT_DIR]      # default: ./validation-evidence
#
# Requires: Docker + Compose, backend venv with deps installed, Node/npm for the
# frontend build. Exit code is 0 only if the smoke test, full suite, pipeline
# trace and — when API keys are present — the OCR accuracy gate all pass.
#
# OCR_BENCH_REPEAT=N controls the provider bench's rounds per document (default 1).
# The bench makes real, billable provider calls; it is skipped without API keys.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

OUT="${1:-$ROOT/validation-evidence}"
mkdir -p "$OUT"
TOOLS="$SCRIPT_DIR/validation"

# Resolve interpreter + load env
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then PY="$ROOT/backend/.venv/bin/python"; else PY="python3"; fi
if [[ -f "$ROOT/backend/.env" ]]; then set -a; source "$ROOT/backend/.env"; set +a; fi
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db}"

OCR_FAILED=0
HOSTID="Darwin $(uname -r) $(uname -m)"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
TAG="$(git describe --tags 2>/dev/null || echo untagged)"
DATESTR="$(date +%Y-%m-%d)"
strip_ansi() { sed -E $'s/\x1b\\[[0-9;]*m//g'; }
hdr() { # hdr "<title>" "<command>" "<result>"
  printf '%s\n' "ACRA MES — $1" \
    "Captured : $DATESTR  (host: $HOSTID)" \
    "Repo     : acra_dev @ $TAG ($SHA)" \
    "Command  : $2" \
    "Result   : $3" \
    "-------------------------------------------------------------------------------"
}
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
say "1/7  Environment snapshot"
{
  echo "ACRA MES — validation environment snapshot"
  echo "Captured: $DATESTR (host: $HOSTID)"
  echo "Repo: acra_dev @ $TAG ($SHA)"
  echo
  printf '%-8s: %s\n' "Python"  "$($PY --version 2>&1)"
  printf '%-8s: %s\n' "Node"    "$(node --version 2>&1)"
  printf '%-8s: %s\n' "npm"     "$(npm --version 2>&1)"
  printf '%-8s: %s\n' "Docker"  "$(docker --version 2>&1)"
  printf '%-8s: %s\n' "Compose" "$(docker compose version --short 2>&1)"
  printf '%-8s: %s\n' "Postgres" "$(docker compose exec -T db postgres --version 2>&1 | tr -d '\r')"
} > "$OUT/environment.txt"

say "2/7  API route inventory"
( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/dump_routes.py" ) > "$OUT/api-routes.txt"

say "3/7  Reset + seed database (clean deterministic state)"
./scripts/reset-db-and-seed.sh > "$OUT/.reseed.log" 2>&1 && echo "  reset + seed OK" || { echo "  reset FAILED"; tail "$OUT/.reseed.log"; exit 1; }

say "4/7  Smoke test (end-to-end)"
{ hdr "smoke-test capture (clean-state end-to-end run)" "./scripts/smoke-test.sh" "see run below";
  SMOKE_SKIP_RESET=1 ./scripts/smoke-test.sh 2>&1 | strip_ansi; } > "$OUT/smoke-test-output.log"
grep -q "SMOKE TEST PASSED" "$OUT/smoke-test-output.log" && echo "  smoke PASSED" || { echo "  smoke FAILED"; exit 1; }

say "5/7  Full backend suite + coverage"
{ hdr "full backend test suite + coverage" "pytest tests/ --cov=app --cov-report=term-missing -q  (DATABASE_URL on :5433)" "see run below";
  ( cd "$ROOT/backend" && "$PY" -m pytest tests/ --cov=app --cov-report=term-missing -q 2>&1 | strip_ansi ); } > "$OUT/backend-suite-coverage.log"
grep -qE "[0-9]+ passed" "$OUT/backend-suite-coverage.log" && echo "  suite: $(grep -E '[0-9]+ passed' "$OUT/backend-suite-coverage.log" | tail -1)"

say "6/7  Boot backend for live captures"
( cd "$ROOT/backend" && exec "$(dirname "$PY")/uvicorn" app.main:app --port 8000 ) > "$OUT/.backend.log" 2>&1 &
BPID=$!
trap '[[ -n "${BPID:-}" ]] && kill "$BPID" 2>/dev/null' EXIT
for _ in $(seq 1 30); do curl -sf localhost:8000/health >/dev/null 2>&1 && break; sleep 1; done

say "    6a  Data-pipeline integrity trace"
{ hdr "data-pipeline integrity trace" "scripts/validation/pipeline_trace.py (real HTTP vs live backend :8000)" "see run below";
  ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/pipeline_trace.py" 2>&1 ); } > "$OUT/data-pipeline-validation.log"
grep -q "ALL INTEGRITY CHECKS PASSED" "$OUT/data-pipeline-validation.log" && echo "  pipeline trace PASSED" || echo "  pipeline trace had failures (see log)"

say "    6b  Real OCR round-trip (accuracy gate)"
if [[ -n "${GEMINI_API_KEY:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  { hdr "real OCR round-trip (vision-LLM BOL extraction, gated vs recorded baseline)" "scripts/validation/ocr_roundtrip.py (POST /api/v1/deliveries/ocr, live provider calls)" "see run below";
    echo; ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/ocr_roundtrip.py" "$OUT/ocr-corpus" 2>&1 ); } > "$OUT/ocr-roundtrip.txt"
  if grep -q "OCR ACCURACY GATE PASSED" "$OUT/ocr-roundtrip.txt"; then
    echo "  OCR accuracy gate PASSED"
  else
    echo "  OCR accuracy gate FAILED (see $OUT/ocr-roundtrip.txt)"; OCR_FAILED=1
  fi
else
  echo "ACRA MES — real OCR round-trip SKIPPED (no GEMINI_API_KEY / ANTHROPIC_API_KEY in backend/.env)." > "$OUT/ocr-roundtrip.txt"
  echo "  OCR round-trip SKIPPED (no API key)"
fi

say "    6c  API latency benchmark"
# Writes its own provenance-stamped artifacts via app.core.benchmark, so no hdr() wrapper here.
( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/api_latency_bench.py" "$OUT" ) \
  > "$OUT/api-latency-bench.log" 2>&1 \
  && echo "  API latency benchmark captured" \
  || { echo "  API latency benchmark FAILED (see api-latency-bench.log)"; tail -5 "$OUT/api-latency-bench.log"; }

say "    6d  Comparative concurrency study (A8-5)"
# Also self-provenanced, so no hdr() wrapper. A reduced sweep: the committed evidence run uses the
# full 2,4,8,16,32 x 5, which takes minutes and is not what a validation pass is for.
# Safe against the seeded database — every row it creates is uuid-tagged and torn down by id.
( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/concurrency_bench.py" "$OUT" \
    --levels 2,8,32 --rounds 3 ) \
  > "$OUT/concurrency-bench.log" 2>&1 \
  && echo "  Concurrency ablation captured" \
  || { echo "  Concurrency ablation FAILED (see concurrency-bench.log)"; tail -5 "$OUT/concurrency-bench.log"; }

say "    6e  OCR provider comparison bench (A8-4)"
if [[ -n "${GEMINI_API_KEY:-}" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
  ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" -m scripts.ocr_bench.run_bench \
      --provider both --repeat "${OCR_BENCH_REPEAT:-1}" --out "$OUT/ocr-bench" --quiet ) \
    > "$OUT/.ocr-bench.log" 2>&1 \
    && echo "  provider comparison captured ($OUT/ocr-bench/)" \
    || { echo "  provider comparison FAILED"; tail -5 "$OUT/.ocr-bench.log"; }
  rm -f "$OUT/.ocr-bench.log"
else
  echo "  provider comparison SKIPPED (needs BOTH GEMINI_API_KEY and ANTHROPIC_API_KEY)"
fi

say "7/7  Done"
kill "$BPID" 2>/dev/null; BPID=""
rm -f "$OUT/.reseed.log" "$OUT/.backend.log"
echo "Artifacts written to: $OUT"
ls -1 "$OUT"

# The header promises "exit code is 0 only if ... the OCR accuracy gate" passes. `ls` above always
# succeeds, so without this the script reported success even after printing "OCR accuracy gate
# FAILED" — the exact shape of defect ACR-36 set out to remove, reintroduced in the harness that
# runs the gate.
if [[ "$OCR_FAILED" -ne 0 ]]; then
  echo
  echo "FAILED — the OCR accuracy gate regressed; see $OUT/ocr-roundtrip.txt"
  exit 1
fi
