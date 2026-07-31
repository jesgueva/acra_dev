#!/usr/bin/env bash
# Reset local Docker Postgres (wipes volume), apply migrations, and run seed_fake_data.py.
#
# Usage (from repo root):
#   ./scripts/reset-db-and-seed.sh
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
# Resolve the actual data volume from the db container before removing it, so the right volume is
# wiped regardless of what the compose project is named. `rm --volumes` alone only drops anonymous
# volumes, never the named one.
#
# The `|| true` on both lookups is load-bearing: this script runs under `set -euo pipefail`, and
# on a fresh clone (or with the daemon down) `docker compose ps` exits non-zero, which would abort
# the script here with no message at all instead of failing later with a useful one. An empty
# result is a legitimate answer — it just means there is no volume to wipe yet.
db_container="$(docker compose ps -aq db 2>/dev/null | head -1 || true)"
db_volume=""
if [[ -n "$db_container" ]]; then
  db_volume="$(docker inspect \
    -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' \
    "$db_container" 2>/dev/null || true)"
fi

docker compose rm --stop --force --volumes db >/dev/null 2>&1 || true
if [[ -n "$db_volume" ]]; then
  docker volume rm -f "$db_volume" >/dev/null 2>&1 || true
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
  "$PY" scripts/seed_fake_data.py
)

echo "==> Done. Default demo logins: admin / admin123, supervisor1 / demo123 (see seed script)."
