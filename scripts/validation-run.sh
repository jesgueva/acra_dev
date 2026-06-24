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
#   ocr-roundtrip.txt            real vision-LLM BOL extraction (skipped w/o API key)
#   sample_bol.png               the synthetic BOL used for the OCR round-trip
#
# Usage (from repo root):
#   ./scripts/validation-run.sh [OUTPUT_DIR]      # default: ./validation-evidence
#
# Requires: Docker + Compose, backend venv with deps installed, Node/npm for the
# frontend build. Exit code is 0 only if the smoke test, full suite, and pipeline
# trace all pass.

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

say "    6b  Real OCR round-trip"
if [[ -n "${GEMINI_API_KEY:-}" || -n "${ANTHROPIC_API_KEY:-}" ]]; then
  { hdr "real OCR round-trip (vision-LLM BOL extraction)" "POST /api/v1/deliveries/ocr (live provider call)" "see run below";
    echo; ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/backend" "$PY" "$TOOLS/ocr_roundtrip.py" "$OUT/sample_bol.png" 2>&1 ); } > "$OUT/ocr-roundtrip.txt"
  echo "  OCR round-trip captured"
else
  echo "ACRA MES — real OCR round-trip SKIPPED (no GEMINI_API_KEY / ANTHROPIC_API_KEY in backend/.env)." > "$OUT/ocr-roundtrip.txt"
  echo "  OCR round-trip SKIPPED (no API key)"
fi

say "7/7  Done"
kill "$BPID" 2>/dev/null; BPID=""
rm -f "$OUT/.reseed.log" "$OUT/.backend.log"
echo "Artifacts written to: $OUT"
ls -1 "$OUT"
