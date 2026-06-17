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

Install these before you start. Versions below are what the baseline was verified against
(see [`docs/architecture.md`](docs/architecture.md) for the full snapshot); nearby versions work.

- **Python** ≥ 3.11 (verified on 3.13)
- **Node.js** ≥ 20 (verified on 24) + npm
- **Docker** with the Compose plugin (`docker compose`) — used for PostgreSQL
- **git**

You do **not** need a local PostgreSQL install — Docker Compose provides it on host port **5433**.

---

## Quickstart

A peer should be able to go from a clean clone to a running stack with the steps below.

```bash
# 1. Clone
git clone git@github.com:jesgueva/acra_dev.git
cd acra_dev

# 2. Environment files (copy templates, then fill in secrets — see "Environment" below)
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 3. Backend dependencies (isolated virtualenv)
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
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

# Frontend tests / lint / build
cd frontend && npm test
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
├── scripts/            # reset-db-and-seed.sh, smoke-test.sh
├── docs/               # architecture.md, RISK_LOG.md
├── docker-compose.yml  # PostgreSQL 15 on host port 5433
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
