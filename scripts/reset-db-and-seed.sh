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

echo "==> Stopping Postgres and removing data volume (docker compose down -v)..."
docker compose down -v

echo "==> Starting Postgres..."
docker compose up -d

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
