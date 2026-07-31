#!/usr/bin/env bash
# Reset local Docker Postgres (wipes volume), apply migrations, and run seed_fake_data.py.
#
# Usage (from repo root):
#   ./scripts/reset-db-and-seed.sh                  # the demo fixture (scale 1)
#   ./scripts/reset-db-and-seed.sh --scale 50       # 50x volume, for benchmarking
#   ./scripts/reset-db-and-seed.sh --deliveries 480 --work-orders 0 --materials 60
#
# Arguments are forwarded verbatim to seed_fake_data.py; run it with --help for the full set.
#
# Requires: Docker with Compose, Python deps installed for backend (see CLAUDE.md).
# Expects Postgres from docker-compose.yml on host port 5433 unless DATABASE_URL overrides.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

echo "==> Stopping Postgres and removing its data volume..."
# Everything here is scoped to `db` on purpose. Since ACR-42 the compose file also defines
# migrate/backend/frontend, so the `docker compose down -v` this used to run would tear down a
# developer's entire containerized stack — including the one README's "Quickstart A — Docker"
# tells them to bring up. This script exists to give a HOST-run backend a clean database, so it
# must touch Postgres and nothing else.
#
# The volume is resolved by Compose's own project/volume LABELS rather than by inspecting a running
# db container's mounts. That distinction matters: after a plain `docker compose down` — which this
# repo's README documents as "stop, keep data" — the container is gone but the volume remains, and
# a container-inspection lookup finds nothing and silently skips the wipe, leaving stale data
# behind while the script cheerfully reports success. Labels are present whether or not any
# container exists.
#
# The `|| true` guards are load-bearing: this script runs under `set -euo pipefail`, and on a fresh
# clone (or with the daemon down) these commands exit non-zero, which would abort the script here
# with no message at all instead of failing later with a useful one. An empty result is a
# legitimate answer — it just means there is no volume to wipe yet.
compose_project="${COMPOSE_PROJECT_NAME:-}"
if [[ -z "$compose_project" ]]; then
  # Exactly two leading spaces: compose emits the top-level project name at that indent, while the
  # nested network/volume `"name"` keys (which carry the project PREFIX, not the project) sit at
  # six. Matching loosely and taking the first hit would work today only by ordering luck.
  compose_project="$(docker compose config --format json 2>/dev/null \
    | sed -n 's/^  "name": *"\([^"]*\)".*/\1/p' | head -1 || true)"
fi

# `rm --volumes` only drops ANONYMOUS volumes, never the named one, so the named volume still has
# to go explicitly below. `rm` (rather than `down`) is what keeps this from cascading into the
# backend/frontend containers that depend on db.
docker compose rm --stop --force --volumes db >/dev/null 2>&1 || true

if [[ -n "$compose_project" ]]; then
  docker volume ls -q \
    --filter "label=com.docker.compose.project=${compose_project}" \
    --filter "label=com.docker.compose.volume=acra-postgres-data" 2>/dev/null \
    | while read -r volume; do
        [[ -n "$volume" ]] && docker volume rm -f "$volume" >/dev/null 2>&1
      done || true
fi

echo "==> Starting Postgres..."
docker compose up -d db

echo "==> Waiting for Postgres to accept connections..."
ready=0
for _ in $(seq 1 60); do
  if docker compose exec -T db pg_isready -U postgres -d acra_db >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Timed out waiting for Postgres. Check: docker compose logs db" >&2
  exit 1
fi

# DATABASE_URL: prefer env, then backend/.env, then Docker Compose default (port 5433).
if [[ -f "$ROOT/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/backend/.env"
  set +a
fi
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db}"

echo "==> Applying migrations (alembic upgrade head)..."
(
  cd "$ROOT/backend" || exit 1
  # Prefer the venv's alembic entrypoint; `python -m alembic` fails on some installs.
  _alembic="$(dirname "$PY")/alembic"
  if [[ -x "$_alembic" ]]; then
    "$_alembic" upgrade head
  else
    "$PY" -m alembic upgrade head
  fi
)

echo "==> Seeding fake data..."
(
  cd "$ROOT/backend"
  "$PY" scripts/seed_fake_data.py "$@"
)

echo "==> Done. Default demo logins: admin / admin123, supervisor1 / demo123 (see seed script)."
