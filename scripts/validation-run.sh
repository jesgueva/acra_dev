#!/usr/bin/env bash
# validation-run.sh — reproducible evidence capture for the Early Implementation
# Validation Package (Hard Stop 3) and the Midpoint Technical Evidence Review (Hard Stop 4).
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
#   concurrency-*.json/.txt      four-arm stock-drawdown ablation (A8-5 comparative study)
#   ocr-bench/ocr-bench.json     gemini vs claude head-to-head, machine-readable (A8-4)
#   ocr-bench/ocr-bench.md       the same comparison as a table for the writeup
#
# See docs/architecture.md#measurement-points-a8-7 for where each stage (6a-6f) below sits in the
# system decomposition — which component boundary it crosses and what it measures.
#
# Usage (from repo root):
#   ./scripts/validation-run.sh [OUTPUT_DIR]      # default: ./validation-evidence
#
# Requires: Docker + Compose, backend venv with deps installed, Node/npm for the
# frontend build.
#
# ---------------------------------------------------------------------------
# Sweep profile — ACRA_BENCH_PROFILE=quick (default) | publication
# ---------------------------------------------------------------------------
# `quick` keeps a validation pass to a few minutes. `publication` runs the FULL sweeps that the
# A8 evidence tables are built from — the parameters below are the single source of truth for
# those numbers, so a reader can reproduce a published table with one command instead of
# reconstructing the flags by hand:
#
#   ACRA_BENCH_PROFILE=publication ./scripts/validation-run.sh
#
#                     quick                    publication
#   6d concurrency    2,8,32 x 3 rounds        2,4,8,16,32 x 5 rounds
#   6e OCR bench      1 round/doc, no pacing   3 rounds/doc, 13s gemini pacing (free-tier 5 rpm)
#   6f aggregation    1k,10k x 50 samples      1k,10k,50k,200k x 100 samples
#
# Publication runs take well over an hour and make real, billable provider calls.
#
# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------
# 0 only if the reset+seed, smoke test, full backend suite, pipeline trace and — when API keys are
# present — the OCR accuracy gate all pass. Under ACRA_BENCH_PROFILE=publication the benchmark
# stages (6c-6f) must ALSO succeed, because there the artifacts are the deliverable; under `quick`
# a benchmark failure warns but does not fail the run, since a validation pass is not an evidence
# capture and the benchmarks need a scratch database the pass does not require.
#
# ACRA_VALIDATION_PORT=N moves the throwaway uvicorn the live stages (6a-6c) measure. The script
# refuses to start if the port is already bound: the health poll cannot tell its own backend from
# somebody else's, so a busy port would silently publish measurements of a different process.
#
# OCR_BENCH_REPEAT / OCR_BENCH_DELAY override the profile's provider-bench rounds and pacing.

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

# --- Sweep profile ---------------------------------------------------------
# The published A8 tables were produced by parameters this script did not carry, so they could not
# be reproduced from the repo. They live here now; see the header for the quick/publication matrix.
PROFILE="${ACRA_BENCH_PROFILE:-quick}"
case "$PROFILE" in
  quick)
    CONC_LEVELS="2,8,32";                     CONC_ROUNDS=3
    AGG_LOT_STEPS="1000,10000";               AGG_SAMPLES=50
    OCR_REPEAT="${OCR_BENCH_REPEAT:-1}";      OCR_DELAY="${OCR_BENCH_DELAY:-0}"
    ;;
  publication)
    CONC_LEVELS="2,4,8,16,32";                CONC_ROUNDS=5
    AGG_LOT_STEPS="1000,10000,50000,200000";  AGG_SAMPLES=100
    OCR_REPEAT="${OCR_BENCH_REPEAT:-3}";      OCR_DELAY="${OCR_BENCH_DELAY:-13}"
    ;;
  *)
    echo "validation-run.sh: unknown ACRA_BENCH_PROFILE '$PROFILE' (expected: quick | publication)" >&2
    exit 2
    ;;
esac

OCR_FAILED=0
BENCH_FAILED=0
PORT="${ACRA_VALIDATION_PORT:-8000}"
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
say "0/7  Profile: $PROFILE  (backend port $PORT)"
printf '     concurrency %s x %s rounds · aggregation %s x %s samples · ocr %s round(s), %ss pacing\n' \
  "$CONC_LEVELS" "$CONC_ROUNDS" "$AGG_LOT_STEPS" "$AGG_SAMPLES" "$OCR_REPEAT" "$OCR_DELAY"

say "1/7  Environment snapshot"
{
  echo "ACRA MES — validation environment snapshot"
  echo "Captured: $DATESTR (host: $HOSTID)"
  echo "Repo: acra_dev @ $TAG ($SHA)"
  # Which sweep produced the sibling artifacts. Without this a reader holding a results table cannot
  # tell a quick pass from a publication capture, and the two disagree.
  echo "Profile: $PROFILE (concurrency $CONC_LEVELS x$CONC_ROUNDS · aggregation $AGG_LOT_STEPS x$AGG_SAMPLES · ocr x$OCR_REPEAT @${OCR_DELAY}s)"
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
# The header promises the suite gates the exit code. It never did: this grep reported the result and
# threw it away, so a red suite still exited 0 — the same swallowed-status shape as the OCR gate below.
if grep -qE "^[0-9]+ (failed|error)|[0-9]+ failed" "$OUT/backend-suite-coverage.log"; then
  echo "  suite FAILED: $(grep -E '[0-9]+ (failed|passed)' "$OUT/backend-suite-coverage.log" | tail -1)"
  exit 1
fi
grep -qE "[0-9]+ passed" "$OUT/backend-suite-coverage.log" \
  && echo "  suite: $(grep -E '[0-9]+ passed' "$OUT/backend-suite-coverage.log" | tail -1)" \
  || { echo "  suite produced no pass count — see $OUT/backend-suite-coverage.log"; exit 1; }

say "6/7  Boot backend for live captures"
# Refuse a busy port rather than racing it. curl cannot tell our uvicorn from a container already
# serving :8000, so the health poll below would go green against a foreign process and stages 6a-6c
# would publish measurements of code that is not this checkout.
if curl -sf --max-time 2 "localhost:$PORT/health" >/dev/null 2>&1; then
  echo "  port $PORT is already serving /health — refusing to measure a process this run did not start."
  echo "  Stop it, or re-run with ACRA_VALIDATION_PORT=<free port>."
  exit 1
fi
( cd "$ROOT/backend" && exec "$(dirname "$PY")/uvicorn" app.main:app --port "$PORT" ) > "$OUT/.backend.log" 2>&1 &
BPID=$!
trap '[[ -n "${BPID:-}" ]] && kill "$BPID" 2>/dev/null' EXIT
export ACRA_API_BASE="http://localhost:$PORT" ACRA_API_URL="http://localhost:$PORT"
for _ in $(seq 1 30); do curl -sf "localhost:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
if ! curl -sf --max-time 2 "localhost:$PORT/health" >/dev/null 2>&1; then
  echo "  backend failed to come up on :$PORT"; tail -20 "$OUT/.backend.log"; exit 1
fi

say "    6a  Data-pipeline integrity trace"
{ hdr "data-pipeline integrity trace" "scripts/validation/pipeline_trace.py (real HTTP vs live backend :8000)" "see run below";
  ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/pipeline_trace.py" 2>&1 ); } > "$OUT/data-pipeline-validation.log"
# Also promised by the header and also never enforced — a failed integrity check printed a warning
# and the run still exited 0.
grep -q "ALL INTEGRITY CHECKS PASSED" "$OUT/data-pipeline-validation.log" \
  && echo "  pipeline trace PASSED" \
  || { echo "  pipeline trace FAILED (see $OUT/data-pipeline-validation.log)"; exit 1; }

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
  || { echo "  API latency benchmark FAILED (see api-latency-bench.log)"; tail -5 "$OUT/api-latency-bench.log"; BENCH_FAILED=1; }

say "    6d  Comparative concurrency study (A8-5)  [profile: $PROFILE — levels $CONC_LEVELS x $CONC_ROUNDS rounds]"
# Also self-provenanced, so no hdr() wrapper. Sweep parameters come from the profile block at the
# top; `publication` is what the A8 evidence tables are built from.
# Safe against the seeded database — every row it creates is uuid-tagged and torn down by id.
( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/concurrency_bench.py" "$OUT" \
    --levels "$CONC_LEVELS" --rounds "$CONC_ROUNDS" ) \
  > "$OUT/concurrency-bench.log" 2>&1 \
  && echo "  Concurrency ablation captured" \
  || { echo "  Concurrency ablation FAILED (see concurrency-bench.log)"; tail -5 "$OUT/concurrency-bench.log"; BENCH_FAILED=1; }

say "    6e  OCR provider comparison bench (A8-4)"
# Self-provenanced via run_bench's own run-metadata block, so no hdr() wrapper here (same as 6c/6d).
if [[ -n "${GEMINI_API_KEY:-}" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
  # The scratch log is removed only on success: run_bench writes ocr-bench.json/.md just on the
  # happy path, so deleting it unconditionally left a failed run with no evidence at all — in the
  # one case where the evidence matters most. 6c and 6d already retain theirs on failure.
  if ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" -m scripts.ocr_bench.run_bench \
        --provider both --repeat "$OCR_REPEAT" --delay "$OCR_DELAY" --out "$OUT/ocr-bench" --quiet ) \
      > "$OUT/ocr-bench.log" 2>&1; then
    echo "  provider comparison captured ($OUT/ocr-bench/)"
    rm -f "$OUT/ocr-bench.log"
  else
    echo "  provider comparison FAILED (see $OUT/ocr-bench.log)"; tail -5 "$OUT/ocr-bench.log"; BENCH_FAILED=1
  fi
else
  echo "  provider comparison SKIPPED (needs BOTH GEMINI_API_KEY and ANTHROPIC_API_KEY)"
  # A publication run exists to produce this artifact; silently shipping without it is the failure
  # mode the profile is meant to prevent.
  [[ "$PROFILE" == "publication" ]] && BENCH_FAILED=1
fi

say "    6f  Aggregation benchmark at volume (A8-6)  [profile: $PROFILE — lots $AGG_LOT_STEPS x $AGG_SAMPLES samples]"
# Also self-provenanced, so no hdr() wrapper. Sweep parameters come from the profile block at the
# top; `publication` goes to 200 000 lots and is the run the A8 table reports. Everything the
# benchmark creates is tagged and torn down, and its index state is restored on the way out.
( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/aggregation_bench.py" "$OUT" \
    --lot-steps "$AGG_LOT_STEPS" --samples "$AGG_SAMPLES" ) \
  > "$OUT/aggregation-bench.log" 2>&1 \
  && echo "  Aggregation benchmark captured" \
  || { echo "  Aggregation benchmark FAILED (see aggregation-bench.log)"; tail -5 "$OUT/aggregation-bench.log"; BENCH_FAILED=1; }

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

# Under `publication` the benchmark artifacts ARE the deliverable, so a missing one is a failed run.
# Under `quick` they are a bonus: the benchmarks want a scratch database a validation pass does not
# require, and failing the pass for that would train the reader to ignore the exit code.
if [[ "$BENCH_FAILED" -ne 0 ]]; then
  echo
  if [[ "$PROFILE" == "publication" ]]; then
    echo "FAILED — a benchmark stage did not produce its artifact; see the *-bench.log files in $OUT"
    exit 1
  fi
  echo "NOTE — a benchmark stage did not produce its artifact (profile: quick, not fatal)."
  echo "       Re-run with ACRA_BENCH_PROFILE=publication for an evidence capture."
fi
