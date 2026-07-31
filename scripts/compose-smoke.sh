#!/usr/bin/env bash
# compose-smoke.sh — prove the containerized stack actually works (ACR-42 / A10-1).
#
# Complements scripts/smoke-test.sh, which exercises the stack as HOST processes. This one asserts
# the same core path against `docker compose`, plus the container-specific failure modes that a
# host run cannot catch:
#
#   * migrations applied by the one-shot `migrate` service, not by a human running alembic
#   * the two-backend-URL split (see frontend/Dockerfile) — the trap that leaves a stack reporting
#     healthy while every login fails
#   * a clean-volume start, which is what a reviewer following the README actually does
#
# Usage (from repo root):
#   ./scripts/compose-smoke.sh                 # default ports, project "acra-smoke"
#   COMPOSE_PROJECT=acr42 ACRA_DB_PORT=5442 ACRA_BACKEND_PORT=8042 ACRA_FRONTEND_PORT=3042 \
#     ./scripts/compose-smoke.sh
#
# Flags:
#   SMOKE_KEEP_UP=1     leave the stack running afterwards (for manual poking)
#   SMOKE_NO_BUILD=1    reuse existing images instead of rebuilding
#
# Exits 0 only if every stage passes.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PROJECT="${COMPOSE_PROJECT:-acra-smoke}"

# Distinct defaults from the documented ones so a smoke run never collides with a stack the
# developer already has up. Overridable for CI or a busy host.
export ACRA_DB_PORT="${ACRA_DB_PORT:-5533}"
export ACRA_BACKEND_PORT="${ACRA_BACKEND_PORT:-8100}"
export ACRA_FRONTEND_PORT="${ACRA_FRONTEND_PORT:-3100}"
export ACRA_DB_CONTAINER="${ACRA_DB_CONTAINER:-${PROJECT}-db}"
export ACRA_MIGRATE_CONTAINER="${ACRA_MIGRATE_CONTAINER:-${PROJECT}-migrate}"
export ACRA_BACKEND_CONTAINER="${ACRA_BACKEND_CONTAINER:-${PROJECT}-backend}"
export ACRA_FRONTEND_CONTAINER="${ACRA_FRONTEND_CONTAINER:-${PROJECT}-frontend}"

API="http://localhost:${ACRA_BACKEND_PORT}"
WEB="http://localhost:${ACRA_FRONTEND_PORT}"
DC=(docker compose -p "$PROJECT")

FAILURES=0
step()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
pass()  { printf '    \033[32mPASS\033[0m %s\n' "$*"; }
fail()  { printf '    \033[31mFAIL\033[0m %s\n' "$*"; FAILURES=$((FAILURES + 1)); }

cleanup() {
  if [[ "${SMOKE_KEEP_UP:-0}" == "1" ]]; then
    printf '\nSMOKE_KEEP_UP=1 — leaving the stack up. Tear down with:\n  %s down -v\n' "${DC[*]}"
    return
  fi
  step "Tearing down"
  "${DC[@]}" --profile seed down -v --remove-orphans >/dev/null 2>&1
}
trap cleanup EXIT

# ---------------------------------------------------------------------------- preflight
step "Preflight"
if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon is not running"
  exit 1
fi
pass "Docker daemon is up"

# Start from a genuinely clean volume — a stale one hides migration bugs.
"${DC[@]}" --profile seed down -v --remove-orphans >/dev/null 2>&1
pass "cleared any previous ${PROJECT} stack"

# ---------------------------------------------------------------------------- bring up
step "Starting the stack (db -> migrate -> backend -> frontend)"
UP_ARGS=(up -d --wait)
[[ "${SMOKE_NO_BUILD:-0}" == "1" ]] || UP_ARGS+=(--build)

if "${DC[@]}" "${UP_ARGS[@]}"; then
  pass "compose up --wait reported every service healthy"
else
  fail "compose up failed"
  "${DC[@]}" ps
  "${DC[@]}" logs --tail 40
  exit 1
fi

# ---------------------------------------------------------------------------- migrations
step "Migrations ran in the one-shot migrate service"
MIGRATE_EXIT="$("${DC[@]}" ps -a --format json migrate 2>/dev/null \
  | sed -n 's/.*"ExitCode":\([0-9-]*\).*/\1/p' | head -1)"
if [[ "$MIGRATE_EXIT" == "0" ]]; then
  pass "migrate exited 0"
else
  fail "migrate exited ${MIGRATE_EXIT:-<unknown>}"
  "${DC[@]}" logs migrate --tail 30
fi

CURRENT="$("${DC[@]}" run --rm --no-deps -T \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/acra_db \
  backend alembic current 2>/dev/null | tr -d '\r')"
if grep -q "head" <<<"$CURRENT"; then
  pass "alembic reports head: $(tr '\n' ' ' <<<"$CURRENT" | tail -c 60)"
else
  fail "alembic is not at head: ${CURRENT:-<empty>}"
fi

# ---------------------------------------------------------------------------- backend
step "Backend API"
if [[ "$(curl -fsS -o /dev/null -w '%{http_code}' "${API}/health")" == "200" ]]; then
  pass "GET ${API}/health -> 200"
else
  fail "GET ${API}/health did not return 200"
fi

if curl -fsS "${API}/openapi.json" | grep -q '"/api/v1/auth/login"'; then
  pass "OpenAPI schema served and includes the auth route"
else
  fail "OpenAPI schema missing or incomplete"
fi

# Anonymous reads must be rejected, not served.
ANON="$(curl -s -o /dev/null -w '%{http_code}' "${API}/api/v1/inventory")"
if [[ "$ANON" == "401" || "$ANON" == "403" ]]; then
  pass "unauthenticated read rejected (${ANON})"
else
  fail "unauthenticated read returned ${ANON}, expected 401/403"
fi

# ---------------------------------------------------------------------------- seed + auth
step "Seeding demo data (opt-in profile)"
if "${DC[@]}" --profile seed run --rm -T seed >/dev/null 2>&1; then
  pass "seed service completed"
else
  fail "seed service failed"
  "${DC[@]}" --profile seed logs seed --tail 30
fi

step "Authentication through the container network"
TOKEN="$(curl -fsS -X POST "${API}/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' 2>/dev/null \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"

if [[ -n "$TOKEN" ]]; then
  pass "login returned a JWT"
else
  fail "login did not return a token"
fi

if [[ -n "$TOKEN" ]]; then
  AUTHED="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" "${API}/api/v1/inventory")"
  if [[ "$AUTHED" == "200" ]]; then
    pass "authenticated read -> 200"
  else
    fail "authenticated read returned ${AUTHED}"
  fi
fi

# ---------------------------------------------------------------------------- frontend
step "Frontend"
if [[ "$(curl -fsS -o /dev/null -w '%{http_code}' "${WEB}/en/login")" == "200" ]]; then
  pass "GET ${WEB}/en/login -> 200"
else
  fail "GET ${WEB}/en/login did not return 200"
fi

if [[ "$(curl -fsS -o /dev/null -w '%{http_code}' "${WEB}/es/login")" == "200" ]]; then
  pass "GET ${WEB}/es/login -> 200 (locale routing works)"
else
  fail "GET ${WEB}/es/login did not return 200"
fi

# The server-side auth proxy runs INSIDE the network and must reach http://backend:8000.
# A wrong BACKEND_URL fails here and nowhere else.
PROXY="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WEB}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}')"
if [[ "$PROXY" == "200" ]]; then
  pass "server-side auth proxy reached the backend over the compose network"
else
  fail "server-side auth proxy returned ${PROXY} — check BACKEND_URL"
fi

# ---------------------------------------------------------------------------- the URL-split trap
step "Browser bundle points at the host, not the compose network"
# NEXT_PUBLIC_API_URL is compiled into the shipped JS. If it were wired to http://backend:8000 the
# stack would look perfectly healthy above while every browser XHR failed with a DNS error.
# Every chunk, not a `head -N` slice: the whole point is to prove a string is ABSENT, and a
# truncated search can only ever prove it absent from the part we looked at.
BUNDLE="$(curl -fsS "${WEB}/en/login" \
  | grep -o '/_next/static/chunks/[^"]*\.js' | sort -u)"
CHUNK_COUNT="$(printf '%s' "$BUNDLE" | grep -c . || true)"

# Guard the negative assertion. Without this, an empty chunk list (login page failed to load, or
# the markup stopped matching the grep) leaves FOUND_INTERNAL at 0 and the script cheerfully
# reports "does not leak the internal service name" having inspected nothing at all — passing on
# the exact bug this section exists to catch.
if [[ "$CHUNK_COUNT" -eq 0 ]]; then
  fail "no JS chunks found on ${WEB}/en/login — cannot verify the bundle (checks below would be vacuous)"
else
  pass "discovered ${CHUNK_COUNT} JS chunk(s) to scan"

  FOUND_HOST=0
  FOUND_INTERNAL=0
  SCANNED=0
  for chunk in $BUNDLE; do
    BODY="$(curl -fsS "${WEB}${chunk}" 2>/dev/null)" || continue
    SCANNED=$((SCANNED + 1))
    grep -q "localhost:${ACRA_BACKEND_PORT}" <<<"$BODY" && FOUND_HOST=1
    grep -q "backend:8000" <<<"$BODY" && FOUND_INTERNAL=1
  done

  if [[ "$SCANNED" -eq 0 ]]; then
    fail "every chunk fetch failed — nothing was actually inspected"
  else
    if [[ "$FOUND_HOST" == "1" ]]; then
      pass "bundle references localhost:${ACRA_BACKEND_PORT} (${SCANNED} chunks scanned)"
    else
      fail "bundle never references localhost:${ACRA_BACKEND_PORT} — NEXT_PUBLIC_API_URL build arg?"
    fi

    if [[ "$FOUND_INTERNAL" == "0" ]]; then
      pass "bundle does not leak the internal service name"
    else
      fail "bundle contains 'backend:8000' — the browser cannot resolve that"
    fi
  fi
fi

# ---------------------------------------------------------------------------- verdict
step "Result"
if [[ "$FAILURES" -eq 0 ]]; then
  printf '\033[32mAll compose smoke checks passed.\033[0m\n'
  exit 0
fi
printf '\033[31m%d check(s) failed.\033[0m\n' "$FAILURES"
exit 1
