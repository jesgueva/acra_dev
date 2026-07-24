#!/usr/bin/env bash
# smoke-test.sh — minimal end-to-end check that the ACRA MES baseline is runnable.
#
# Proves, in one command, that the project starts and the core pipeline executes:
#   1. PostgreSQL comes up (Docker Compose) and accepts connections
#   2. Alembic migrations apply cleanly and seed data loads
#   3. The FastAPI backend boots and answers /health
#   4. Auth works (login issues a JWT) and RBAC is enforced (401/403 without a token)
#   5. An authenticated API read returns data
#   6. The backend test suite passes (schema + a representative router subset)
#   7. The Next.js frontend produces a production build
#
# Usage (from repo root):
#   ./scripts/smoke-test.sh
#
# Flags (env):
#   SMOKE_SKIP_FRONTEND=1   skip the frontend production build (faster backend-only run)
#   SMOKE_SKIP_RESET=1      assume DB is already migrated+seeded; do not wipe/reseed
#   SMOKE_SKIP_DOCKER=1     DB is managed outside docker-compose.yml (parallel worktrees)
#   SMOKE_BACKEND_PORT=8000 port to boot the backend on (must be free)
#
# Requires: Docker + Compose, and backend deps installed (see README "Setup").
# Exit code is 0 only if every step passes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PORT="${SMOKE_BACKEND_PORT:-8000}"
BASE="http://localhost:${PORT}"
PASS="✓"
FAIL="✗"
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '   %s %s\n' "$PASS" "$*"; }
die()  { printf '   %s %s\n' "$FAIL" "$*" >&2; exit 1; }

# Resolve a Python interpreter (prefer the backend venv).
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi
ALEMBIC="$(dirname "$PY")/alembic"; [[ -x "$ALEMBIC" ]] || ALEMBIC="$PY -m alembic"

# Load backend/.env (DATABASE_URL etc.), then fall back to the Compose default (port 5433).
if [[ -f "$ROOT/backend/.env" ]]; then
  set -a; # shellcheck disable=SC1091
  source "$ROOT/backend/.env"; set +a
fi
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db}"

BACKEND_PID=""
cleanup() { [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
step "1/7  Database — start PostgreSQL and apply migrations + seed"
if [[ "${SMOKE_SKIP_RESET:-0}" == "1" ]]; then
  # SMOKE_SKIP_DOCKER=1 — the database is managed outside this compose file. Parallel worktrees
  # cannot each run it: `container_name: acra-postgres` and host port 5433 are single-occupancy.
  if [[ "${SMOKE_SKIP_DOCKER:-0}" != "1" ]]; then
    docker compose up -d >/dev/null
  fi
  ( cd "$ROOT/backend" && $ALEMBIC upgrade head >/dev/null ) && ok "migrations at head (reset skipped)"
else
  ./scripts/reset-db-and-seed.sh >/tmp/acra_smoke_db.log 2>&1 && ok "DB reset, migrated, and seeded" \
    || die "reset-db-and-seed.sh failed (see /tmp/acra_smoke_db.log)"
fi

# ---------------------------------------------------------------------------
step "2/7  Backend — boot FastAPI (uvicorn) on port ${PORT}"
( cd "$ROOT/backend" && exec "$(dirname "$PY")/uvicorn" app.main:app --port "$PORT" ) \
  >/tmp/acra_smoke_backend.log 2>&1 &
BACKEND_PID=$!
for _ in $(seq 1 30); do
  if curl -sf "$BASE/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

# ---------------------------------------------------------------------------
step "3/7  Health check"
HEALTH="$(curl -sf "$BASE/health")" || die "GET /health did not return 200"
[[ "$HEALTH" == *'"status":"ok"'* ]] && ok "GET /health -> $HEALTH" || die "unexpected /health body: $HEALTH"

# ---------------------------------------------------------------------------
step "4/7  Auth — login issues a JWT, and RBAC blocks anonymous reads"
TOKEN="$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  | "$PY" -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')"
[[ -n "$TOKEN" ]] && ok "POST /api/v1/auth/login -> JWT (${#TOKEN} chars)" || die "login returned no token"

ANON_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/inventory")"
[[ "$ANON_CODE" == "401" || "$ANON_CODE" == "403" ]] \
  && ok "anonymous GET /api/v1/inventory -> $ANON_CODE (RBAC enforced)" \
  || die "anonymous read was not rejected (got $ANON_CODE)"

# ---------------------------------------------------------------------------
step "5/7  Authenticated read returns data"
TOTAL="$(curl -sf "$BASE/api/v1/inventory" -H "Authorization: Bearer $TOKEN" \
  | "$PY" -c 'import sys,json; print(json.load(sys.stdin).get("total",0))')"
[[ "$TOTAL" -gt 0 ]] && ok "GET /api/v1/inventory -> $TOTAL lots" || die "authenticated read returned no rows"

# ---------------------------------------------------------------------------
step "6/7  Backend tests — schema + representative routers"
( cd "$ROOT/backend" && "$PY" -m pytest \
    tests/test_schema.py tests/test_core.py tests/test_auth.py tests/test_inventory.py \
    -q ) && ok "pytest smoke subset passed" || die "pytest smoke subset failed"

# ---------------------------------------------------------------------------
step "7/7  Frontend — production build"
if [[ "${SMOKE_SKIP_FRONTEND:-0}" == "1" ]]; then
  ok "skipped (SMOKE_SKIP_FRONTEND=1)"
else
  ( cd "$ROOT/frontend" && npm run build ) >/tmp/acra_smoke_frontend.log 2>&1 \
    && ok "next build succeeded" \
    || die "frontend build failed (see /tmp/acra_smoke_frontend.log)"
fi

printf '\n\033[1;32mSMOKE TEST PASSED\033[0m — baseline is runnable end to end.\n'
