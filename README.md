# ACRA MES

**ACRA Integrated Manufacturing Execution System** — a state-aware MES for a single-facility
packaging manufacturer. Tracks inbound receiving (with AI-assisted document extraction), live
inventory by lot, work orders, production/forklift worksheets, and shipments, with role-based
access control, an append-only audit trail, and a bilingual (EN/ES) UI.

This is a **monorepo**: a FastAPI backend, a Next.js frontend, and a PostgreSQL database, with
Docker Compose for local infrastructure.

> **Status:** Phase 2 engineering baseline (`v0.2.0-sprint1-baseline`). The Phase 1 feature
> surface is merged and CI-gated; Phase 2 realigns inventory onto an append-only `StockMovement`
> ledger (see [`docs/architecture.md`](docs/architecture.md)).

---

## Tech stack

| Layer | Stack |
|---|---|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript 5, Tailwind CSS v4, shadcn/ui, next-intl, TanStack Query, Axios |
| **Backend** | FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, python-jose (JWT), passlib/bcrypt |
| **Database** | PostgreSQL 15 |
| **AI extraction** | Hosted vision-LLM for receiving-document OCR (Google Gemini → Anthropic Claude fallback) |
| **Tests / CI** | pytest (85% coverage floor), Jest + Testing Library, GitHub Actions |

---

## Prerequisites

**If you run the stack with Docker (below), you only need Docker and git** — Python and Node come
from the images.

For a local (non-container) install, these are the supported versions. They are the *only* versions
named anywhere in this repo — `backend/pyproject.toml` and `.nvmrc` are the machine-readable source
of truth, and `backend/tests/test_packaging.py` fails the build if a doc drifts from them.

- **Python** 3.13 — declared in [`backend/pyproject.toml`](backend/pyproject.toml)
- **Node.js** 24 + npm — declared in [`.nvmrc`](.nvmrc) / [`frontend/.nvmrc`](frontend/.nvmrc)
- **Docker** with the Compose plugin (`docker compose`)
- **git**

You do **not** need a local PostgreSQL install — Docker Compose provides it on host port **5433**.

---

## Quickstart A — Docker (whole stack, no toolchain install)

Clean clone to running system in three commands. Nothing but Docker and git required.

```bash
git clone git@github.com:jesgueva/acra_dev.git
cd acra_dev
cp .env.example .env                            # defaults work as-is for local use

docker compose up -d --build                    # Postgres + migrations + API + web
docker compose --profile seed run --rm seed     # demo data (opt-in)
```

Open **http://localhost:3000** and sign in with a [seeded account](#seeded-demo-logins). The API is
at **http://localhost:8000** (docs at `/docs`).

| Service | What it does |
|---|---|
| `db` | PostgreSQL 15, published on `5433` |
| `migrate` | One-shot `alembic upgrade head`, then exits. The API waits for it to succeed. |
| `backend` | FastAPI on `8000` |
| `frontend` | Next.js production server on `3000` |
| `seed` | Demo data. Behind the `seed` profile, so `up` never repopulates a database by surprise. |

Useful commands:

```bash
docker compose logs -f backend        # follow a service
docker compose run --rm backend pytest tests/   # run the suite with no local Python*
docker compose down                   # stop, keep data
docker compose down -v                # stop and wipe the database volume
./scripts/compose-smoke.sh            # assert the containerized stack end to end
```

\* The backend image is built from `backend/` alone, so the repo-root files the version-parity tests
compare (`.nvmrc`, `frontend/package.json`, `.github/workflows/ci.yml`) are not in it. Those four
tests in `backend/tests/test_packaging.py` skip when run this way and still run on a checkout and in
CI. Everything else runs.

**If a port is already taken** (common — this repo is often checked out into several worktrees),
override it in `.env` or inline:

```bash
ACRA_DB_PORT=5442 ACRA_BACKEND_PORT=8042 ACRA_FRONTEND_PORT=3042 \
  docker compose -p acr42 up -d --build
```

> **Changing `ACRA_BACKEND_PORT` requires `--build`, not just a restart.** `NEXT_PUBLIC_API_URL` is
> compiled into the browser bundle at build time rather than read at runtime, so the frontend image
> is tied to the API port it was built for. This is a property of Next.js's `NEXT_PUBLIC_*`
> handling, not a bug in the compose file.

---

## Quickstart B — Local processes (for active development)

Use this when you want hot reload. Requires the Python and Node versions listed above.

```bash
# 1. Clone
git clone git@github.com:jesgueva/acra_dev.git
cd acra_dev

# 2. Environment files (copy templates, then fill in secrets — see "Environment" below)
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 3. Backend dependencies (isolated virtualenv)
#    requirements.lock is the full resolved set — it is what CI and the containers install, so
#    installing it gets you exactly their versions. Use requirements.txt only when ADDING a
#    dependency, then regenerate the lock (see backend/requirements.lock's header).
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.lock
cd ..

# 4. Frontend dependencies
cd frontend
npm install
cd ..

# 5. Start PostgreSQL, apply migrations, and load demo data (one script)
./scripts/reset-db-and-seed.sh

# 6. Run the backend (terminal 1)
cd backend && ./.venv/bin/uvicorn app.main:app --reload --port 8000

# 7. Run the frontend (terminal 2)
cd frontend && npm run dev
```

Then open **http://localhost:3000** and sign in with a seeded account (below). The API is at
**http://localhost:8000**, with interactive docs at **http://localhost:8000/docs**.

### Seeded demo logins

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Company Admin |
| `supervisor1` | `demo123` | Production Supervisor |
| `clerk1` | `demo123` | Receiving/Shipping Clerk |
| `operator1` / `operator2` | `demo123` | Machine Operator |

> Demo credentials seed a **local** database only. Never reuse them outside local development.

---

## Verify it works (smoke test)

One command takes a clean checkout to a running stack and asserts the core path end to end —
database up, migrations + seed, backend boot, `/health`, login + JWT, RBAC enforcement, an
authenticated read, the backend test subset, and a frontend production build:

```bash
./scripts/smoke-test.sh
```

It exits `0` only if every stage passes. Flags: `SMOKE_SKIP_FRONTEND=1` (backend only),
`SMOKE_SKIP_RESET=1` (don't wipe/reseed), `SMOKE_BACKEND_PORT=8001`.

For a fuller, evidence-capturing pass — environment snapshot, API route inventory, smoke test,
full backend suite + coverage, a **data-pipeline integrity trace**, and a **real OCR round-trip** —
run the validation harness (used for the Hard Stop 3 validation package):

```bash
./scripts/validation-run.sh            # writes artifacts to ./validation-evidence/
```

The OCR round-trip needs `GEMINI_API_KEY` (and optionally `ANTHROPIC_API_KEY`) in `backend/.env`;
it is skipped with a clear notice if no key is present.

---

## Implementation status

What a reader can exercise **right now** vs. what is still partial at this baseline
(`v0.2.0-sprint1-baseline`). Re-verified end to end on 2026-06-23 via `scripts/validation-run.sh`.

| Capability | State | Notes |
|---|---|---|
| Auth (JWT) + RBAC + EN/ES i18n | ✅ Live (UI + API) | Anonymous reads rejected (401/403); privileges resolved per request. |
| Receiving + AI OCR (Gemini → Claude) | ✅ Live (UI + API) | BOL upload auto-fills the form; duplicate-BOL guard; pallet × units leftover reconciliation. |
| Inventory (filter / adjust / split / move / CSV / alerts / trace) | ✅ Live (UI + API) | On-hand stored as integer ×100; per-lot transaction log. |
| Master data (contacts, products), Dashboard | ✅ Live (UI + API) | |
| Work Orders (incl. SERIALIZABLE FIFO allocation), Users, Audit-log read | ⚙️ Backend complete, **UI placeholder** | Endpoints + tests exist; pages render "Coming Soon"; nav links commented out. |
| Shipments | ⚙️ Backend complete, **not reachable** | Endpoints + UI exist, but `shipping.*` privileges are unseeded → 403 for all roles (KI-08). |
| StockMovement ledger (C-04); Production / Forklift worksheets (C-06 / C-07) | 🚧 Phase-2 stub | Ledger model/service/router are placeholders (`501` / `NotImplementedError`, KI-04); inventory still runs on the Phase-1 lot model. |

Known rough edges are tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) and [`docs/RISK_LOG.md`](docs/RISK_LOG.md).

---

## Environment

Configuration is via env files (both are git-ignored; commit only the `.example` templates).

### `backend/.env` — copy from [`backend/.env.example`](backend/.env.example)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy DSN. Use port **5433** with the Docker Compose Postgres. |
| `SECRET_KEY` | JWT signing key — generate a unique random value. |
| `ALGORITHM` | JWT algorithm (`HS256`). |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime. |
| `GEMINI_API_KEY` | Google Gemini key for receiving-document extraction (primary). |
| `ANTHROPIC_API_KEY` | Anthropic Claude key (extraction fallback). |

The AI keys are only exercised by the receiving/OCR flow — the rest of the app runs without them.

### `frontend/.env.local` — copy from [`frontend/.env.local.example`](frontend/.env.local.example)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL the browser calls (default `http://localhost:8000`). |
| `BACKEND_URL` | Backend URL the Next.js server-side auth proxy calls. |

---

## Common commands

```bash
# Backend tests (full suite; needs the DB up + DATABASE_URL set for schema tests)
cd backend && ./.venv/bin/python -m pytest tests/ -q

# Backend tests with coverage (CI enforces an 85% floor on app.*)
cd backend && ./.venv/bin/python -m pytest tests/ --cov=app --cov-report=term-missing

# Frontend tests / lint / build  (no "test" npm script — invoke jest directly, as CI does)
cd frontend && npx jest
cd frontend && npm run lint
cd frontend && npm run build

# Reset the database to clean seeded state (wipes the Docker volume)
./scripts/reset-db-and-seed.sh
```

---

## Repository layout

```
acra_dev/
├── backend/            # FastAPI app (router → service → repository), Alembic, pytest
│   ├── app/            #   main.py, core/ (config, db, security, rbac, audit), models, routers, schemas, services
│   ├── alembic/        #   migrations (versions/)
│   ├── scripts/        #   create_admin.py, seed_fake_data.py
│   └── tests/          #   pytest suite (+ integration/)
├── frontend/           # Next.js 16 App Router + shadcn/ui
│   ├── app/            #   [locale]/ routes, api/auth/ server proxies, layout
│   ├── src/            #   components, contexts, lib, i18n
│   └── messages/       #   next-intl catalogs (en.json, es.json)
├── scripts/            # reset-db-and-seed.sh, smoke-test.sh, validation-run.sh, validation/
├── docs/               # architecture.md, RISK_LOG.md
├── docker-compose.yml  # full stack: db → migrate → backend → frontend (+ seed profile)
├── CHANGELOG.md · KNOWN_ISSUES.md · CONTRIBUTING.md
└── CLAUDE.md           # engineering memory (conventions, patterns)
```

See [`docs/architecture.md`](docs/architecture.md) for how this layout maps to the system design,
and [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch strategy and conventions.

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System decomposition, layering, repo→design map, version snapshot |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch strategy, naming, commits, tags, artifact storage, PR/CI flow |
| [`CHANGELOG.md`](CHANGELOG.md) | Notable changes per release (Keep a Changelog) |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Current known limitations and rough edges |
| [`docs/RISK_LOG.md`](docs/RISK_LOG.md) | Tracked engineering risks and issues |
| [`CLAUDE.md`](CLAUDE.md) | Detailed engineering memory and code conventions |
